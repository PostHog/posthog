"""Starting and following recording deletions on behalf of staff, for the PostHog Admin console."""

import io
import re
import csv
import json
import uuid
import asyncio
import dataclasses
from datetime import datetime, timedelta
from typing import Any
from urllib import parse

from django.conf import settings

import structlog
from dateutil import parser as isoparser
from pydantic import BaseModel
from temporalio import common
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.search_attributes import POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.delete_recordings.object_storage import (
    discard_session_id_chunks,
    store_session_id_chunks,
)
from posthog.temporal.session_replay.delete_recordings.types import (
    DeletionConfig,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithSessionIdsInput,
    RecordingsWithTeamInput,
)

logger = structlog.get_logger(__name__)

WORKFLOW_TYPES = (
    "delete-recordings-with-person",
    "delete-recordings-with-team",
    "delete-recordings-with-query",
    "delete-recordings-with-session-ids",
)
RECENT_RUNS = 20
SESSION_ID_CHUNK_SIZE = 10_000
# Bounds every Temporal read, so a stalled Temporal cannot hold a web worker.
TEMPORAL_READ_TIMEOUT = timedelta(seconds=5)
_QUERY_OPERATOR_LABELS = {"lt": "<", "gt": ">", "lte": "<=", "gte": ">=", "exact": "=", "is_not": "!="}
_QUERY_UNIT_SUFFIXES = {"duration": "s"}


@dataclasses.dataclass(frozen=True)
class ReplayActivityContext(ActivityContextBase):
    reason: str


@frozen
class DeletionRun:
    workflow_id: str
    run_id: str
    workflow_type: str
    status: str
    started: datetime | None
    closed: datetime | None


@frozen
class DeletionRequest:
    """Who asked for a deletion, why, and under which workflow ID."""

    team: Team
    workflow_id: str
    reason: str
    dry_run: bool
    requested_by: User


@frozen
class RecordingFilters:
    date_from: str = ""
    date_to: str = ""
    duration_min: int | None = None
    duration_max: int | None = None
    person_uuid: str = ""
    platform: str = ""

    def is_empty(self) -> bool:
        return (
            not any((self.date_from, self.date_to, self.person_uuid, self.platform))
            and self.duration_min is None
            and self.duration_max is None
        )

    def query(self) -> str:
        """The query string the delete-recordings-with-query workflow reads with parse_qsl."""
        params: list[tuple[str, str]] = []
        if self.date_from:
            params.append(("date_from", self.date_from))
        if self.date_to:
            params.append(("date_to", self.date_to))
        if self.person_uuid:
            params.append(("person_uuid", self.person_uuid))
        properties: list[dict[str, Any]] = []
        if self.duration_min is not None:
            properties.append({"type": "recording", "key": "duration", "operator": "gt", "value": self.duration_min})
        if self.duration_max is not None:
            properties.append({"type": "recording", "key": "duration", "operator": "lt", "value": self.duration_max})
        if self.platform:
            properties.append(
                {"type": "recording", "key": "snapshot_source", "operator": "exact", "value": [self.platform]}
            )
        if properties:
            params.append(("having_predicates", json.dumps(properties)))
        # urlencode escapes "+" and "&", so a date such as 2024-01-01T00:00:00+00:00 reaches the workflow unchanged.
        return parse.urlencode(params)


def normalize_date_filter(value: str) -> str:
    """A date filter in a form the recordings query parses, or ValueError.

    The query falls back to its default date window for a value it cannot parse, such as "null", so a
    deletion with such a value would cover other recordings than staff asked for.
    """
    value = value.strip()
    # A bare integer is ambiguous: "-30" reads as days, but "2024" or "202401" is meant as a date and as
    # days would reach back thousands of days. The query also parses it as an int and fails validation.
    if re.fullmatch(r"-?[0-9]+", value):
        raise ValueError(f"{value!r} has no unit")
    # Only the units posthog.utils.get_delta_mapping_for handles; it is case-sensitive ("m" is months, "M" minutes)
    # and returns no delta for any other unit, or for a unit without a number, which would move the cutoff to now.
    # Without a number only a Start or End of h, d, w, m, q or y moves the date, such as "mStart" for this month.
    # [0-9], not \d: the query reads only ASCII digits, so a number in other digits would move the cutoff to now.
    if re.fullmatch(r"-?[0-9]+[hdwmMsqy](Start|End)?|[hdwmqy](Start|End)", value):
        return value
    try:
        isoparser.isoparse(value)
    except ValueError:
        datetime.strptime(value, "%Y-%m-%d")
    return value


def describe_query(query: str) -> str:
    """A query string as staff and customers read it, for example "date from: -30d, duration < 5s"."""
    parts = []
    for key, value in parse.parse_qsl(query):
        if key not in ("having_predicates", "properties"):
            parts.append(f"{key.replace('_', ' ')}: {value}")
            continue
        try:
            for item in json.loads(value):
                label = item.get("key", "?").replace("_", " ")
                operator = _QUERY_OPERATOR_LABELS.get(item.get("operator", ""), item.get("operator", "?"))
                raw_value = item.get("value", "?")
                shown = ", ".join(raw_value) if isinstance(raw_value, list) else str(raw_value)
                parts.append(f"{label} {operator} {shown}{_QUERY_UNIT_SUFFIXES.get(item.get('key', ''), '')}")
        except (json.JSONDecodeError, TypeError, AttributeError):
            parts.append(f"{key}: {value}")
    return ", ".join(parts) if parts else query


def session_ids_from_csv(content: str) -> list[str]:
    """The session IDs in the first column, without a session_id header row and without repeats, in file order."""
    session_ids = []
    for row in csv.reader(io.StringIO(content)):
        if not row:
            continue
        value = row[0].strip()
        if value and value.lower() != "session_id":
            session_ids.append(value)
    return list(dict.fromkeys(session_ids))


class RecordingDeletions:
    """Starts the delete-recordings Temporal workflows for one team and reads their runs and certificates."""

    @staticmethod
    def workflow_id(team_id: int, form_nonce: uuid.UUID, kind: str, dry_run: bool, scope: str) -> str:
        """One workflow ID per form and input, so a double submit starts one run, and a real run after a dry
        run from the same form starts its own.

        The certificate shows the part after the team ID as its reference, so the run key is a UUID.
        """
        run_key = uuid.uuid5(form_nonce, json.dumps([team_id, kind, dry_run, scope]))
        return f"delete-recordings-{team_id}-{run_key}"

    @staticmethod
    def recent(team_id: int) -> list[DeletionRun] | None:
        """The team's latest runs, or None when Temporal cannot be reached."""
        # The PostHogTeamId search attribute is indexed. A WorkflowId range scan is not, and times out.
        type_clauses = " OR ".join(f'WorkflowType = "{workflow_type}"' for workflow_type in WORKFLOW_TYPES)
        query = f"PostHogTeamId = {team_id} AND ({type_clauses})"

        async def fetch() -> list[DeletionRun]:
            client = await async_connect()
            runs: list[DeletionRun] = []
            async for workflow in client.list_workflows(query=query, rpc_timeout=TEMPORAL_READ_TIMEOUT):
                runs.append(
                    DeletionRun(
                        workflow_id=workflow.id,
                        run_id=workflow.run_id,
                        workflow_type=workflow.workflow_type,
                        status=workflow.status.name if workflow.status else "UNKNOWN",
                        started=workflow.start_time,
                        closed=workflow.close_time,
                    )
                )
                if len(runs) >= RECENT_RUNS:
                    break
            return runs

        try:
            # rpc_timeout does not bound the connect, so one deadline covers the connect and the list.
            return asyncio.run(asyncio.wait_for(fetch(), timeout=TEMPORAL_READ_TIMEOUT.total_seconds()))
        except Exception:
            logger.warning("recording_deletion_runs_unavailable", team_id=team_id, exc_info=True)
            return None

    @staticmethod
    def certificate(team_id: int, workflow_id: str) -> tuple[dict[str, Any] | None, str | None]:
        """The certificate a completed run returned, or None and the reason it cannot be shown."""
        if not workflow_id.startswith(f"delete-recordings-{team_id}-"):
            return None, "This run does not belong to this team."

        async def fetch(client: Client) -> tuple[dict[str, Any] | None, str | None]:
            handle = client.get_workflow_handle(workflow_id)
            description = await handle.describe(rpc_timeout=TEMPORAL_READ_TIMEOUT)
            if description.status != WorkflowExecutionStatus.COMPLETED:
                status = description.status.name.lower().replace("_", " ") if description.status else "unknown"
                return None, f"The run is {status}. Its certificate is ready once it completes."
            return await handle.result(rpc_timeout=TEMPORAL_READ_TIMEOUT), None

        try:
            return asyncio.run(fetch(sync_connect()))
        except Exception:
            logger.exception("recording_deletion_certificate_unavailable", workflow_id=workflow_id)
            return (
                None,
                "Temporal did not return the certificate. Try again, and check the server logs if it fails again.",
            )

    @classmethod
    def start_for_person(cls, request: DeletionRequest, distinct_ids: list[str]) -> None:
        workflow_input = RecordingsWithPersonInput(
            team_id=request.team.pk, distinct_ids=distinct_ids, config=cls._config(request)
        )
        cls._start(
            request, "person", "delete-recordings-with-person", workflow_input, distinct_ids_count=len(distinct_ids)
        )

    @classmethod
    def start_for_team(cls, request: DeletionRequest) -> None:
        workflow_input = RecordingsWithTeamInput(team_id=request.team.pk, config=cls._config(request))
        cls._start(request, "team", "delete-recordings-with-team", workflow_input)

    @classmethod
    def start_for_filters(cls, request: DeletionRequest, filters: RecordingFilters) -> None:
        query = filters.query()
        workflow_input = RecordingsWithQueryInput(team_id=request.team.pk, query=query, config=cls._config(request))
        cls._start(request, "filters", "delete-recordings-with-query", workflow_input, query=query)

    @classmethod
    def start_for_session_ids(cls, request: DeletionRequest, session_ids: list[str], source_filename: str) -> None:
        # Temporal refuses payloads above about 2 MB, so the session IDs go to object storage in chunks.
        # Each attempt writes under its own prefix, so a resubmit that Temporal rejects cannot overwrite the
        # chunks a running workflow with the same ID still reads.
        attempt = f"{request.workflow_id}/{uuid.uuid4()}"
        s3_prefix, total_chunks = store_session_id_chunks(attempt, session_ids, SESSION_ID_CHUNK_SIZE)
        workflow_input = RecordingsWithSessionIdsInput(
            team_id=request.team.pk,
            s3_prefix=s3_prefix,
            total_chunks=total_chunks,
            chunk_size=SESSION_ID_CHUNK_SIZE,
            total_session_ids=len(session_ids),
            config=cls._config(request),
            source_filename=source_filename,
        )
        try:
            cls._start(
                request,
                "session_ids",
                "delete-recordings-with-session-ids",
                workflow_input,
                session_ids_count=len(session_ids),
            )
        except WorkflowAlreadyStartedError:
            # Temporal refused this attempt, so no workflow reads its prefix. Any other error leaves the chunks,
            # because that start may have reached Temporal, and a running workflow would then read them.
            try:
                discard_session_id_chunks(s3_prefix, total_chunks)
            except Exception:
                logger.warning("recording_deletion_chunks_not_discarded", s3_prefix=s3_prefix, exc_info=True)
            raise

    @staticmethod
    def _config(request: DeletionRequest) -> DeletionConfig:
        return DeletionConfig(reason=request.reason, dry_run=request.dry_run, deleted_by=request.requested_by.email)

    @staticmethod
    def _start(
        request: DeletionRequest, kind: str, workflow_name: str, workflow_input: BaseModel, **log_fields: object
    ) -> None:
        """Raises WorkflowAlreadyStartedError when a run with this workflow ID exists, so one form starts one run."""
        team = request.team
        asyncio.run(
            sync_connect().start_workflow(
                workflow_name,
                workflow_input,
                id=request.workflow_id,
                task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
                search_attributes=TypedSearchAttributes(
                    search_attributes=[SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team.pk)]
                ),
                # Temporal reuses a closed workflow's ID by default, so a resubmit after the run ended would run again.
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        )
        # The run has started. A failure to log it must not tell staff that it did not.
        try:
            RecordingDeletions._log_start(request, kind, **log_fields)
        except Exception:
            logger.exception("recording_deletion_start_not_logged", workflow_id=request.workflow_id)

    @staticmethod
    def _log_start(request: DeletionRequest, kind: str, **log_fields: object) -> None:
        team = request.team
        logger.info(
            f"delete_recordings_with_{kind}_triggered",
            team_id=team.pk,
            workflow_id=request.workflow_id,
            dry_run=request.dry_run,
            reason=request.reason,
            triggered_by=request.requested_by.email,
            **log_fields,
        )
        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=request.requested_by,
            was_impersonated=False,
            item_id=request.workflow_id,
            scope="Replay",
            activity="bulk_delete_triggered",
            detail=Detail(
                name=f"Bulk delete recordings ({kind})",
                type=f"admin_delete_{kind}",
                context=ReplayActivityContext(reason=request.reason),
            ),
        )
