import gzip
import base64
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import groupby
from typing import TYPE_CHECKING

from django.utils import timezone

from pydantic import BaseModel, Field, ValidationError

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.paging import Page, PageRequest
from posthog.schema_enums import ProductKey

from products.customer_analytics.backend.facade.contracts import AccountAutomation
from products.workflows.backend.facade.api import get_workflow_names
from products.workflows.backend.facade.workflows import get_workflow

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class RunEvent(BaseModel):
    event: str = ""
    distinct_id: str = ""
    properties: dict[str, object] = Field(default_factory=dict)


class RunContext(BaseModel):
    event: RunEvent = Field(default_factory=RunEvent)
    accountAudience: bool = False


def decode_run_context(value: str) -> RunContext:
    try:
        decoded = value if value.startswith("{") else gzip.decompress(base64.b64decode(value)).decode()
        return RunContext.model_validate_json(decoded)
    except (ValueError, OSError, EOFError, ValidationError):
        return RunContext()


def matches_account(context: RunContext, account_id: str, external_id: str | None) -> bool:
    event = context.event
    if event.event.startswith("$account_"):
        return event.distinct_id == f"account:{account_id}" or (
            external_id is not None and event.properties.get("account_external_id") == external_id
        )
    return (
        context.accountAudience
        and event.event == "$batch_hog_flow_invocation"
        and external_id is not None
        and event.distinct_id == external_id
    )


@frozen
class CompletedWorkflowStep:
    action_id: str | None
    completed_at: datetime


def get_last_completed_step(
    logs: Sequence[tuple[datetime, str]], *, exit_action_ids: set[str]
) -> CompletedWorkflowStep | None:
    completed_step = None
    executing = False
    executing_ids: set[str] = set()
    for timestamp, entries in groupby(logs, key=lambda entry: entry[0]):
        messages = [message for _, message in entries]
        started_ids = {
            message.removeprefix("Executing action ").removeprefix("[Action:").removesuffix("]")
            for message in messages
            if message.startswith("Executing action ")
        }
        started = bool(started_ids)
        failed_or_skipped = any(
            "Errored:" in message
            or "skip" in message.lower()
            or "did not match" in message
            or "would not trigger" in message
            for message in messages
        )
        finished = "Workflow completed" in messages
        moved_ids = {
            message.removeprefix("Workflow moved to action ").removeprefix("[Action:").removesuffix("]")
            for message in messages
            if message.startswith("Workflow moved to action ")
        }
        moved = bool(moved_ids)
        exit_completed = finished and bool((started_ids or executing_ids) & exit_action_ids)
        if (executing or started) and (moved or exit_completed) and not failed_or_skipped:
            completed_ids = (
                (started_ids | executing_ids) & exit_action_ids
                if exit_completed
                else (started_ids | executing_ids) - moved_ids
            )
            completed_step = CompletedWorkflowStep(
                action_id=next(iter(completed_ids)) if len(completed_ids) == 1 else None,
                completed_at=timestamp,
            )
        if failed_or_skipped or moved or finished:
            executing = started and not failed_or_skipped and not finished
        elif started:
            executing = True
        if started or moved or finished:
            executing_ids = started_ids
    return completed_step


def get_expected_resume_at(
    logs: Sequence[tuple[datetime, str]], *, now: datetime, delay_action_ids: set[str]
) -> datetime | None:
    resume_at = None
    current_action_id = None
    prefix = "Workflow will pause until "
    for _, entries in groupby(logs, key=lambda entry: entry[0]):
        messages = [message for _, message in entries]
        pauses = [message.removeprefix(prefix) for message in messages if message.startswith(prefix)]
        action_ids = {
            message.removeprefix(action_prefix).removeprefix("[Action:").removesuffix("]")
            for message in messages
            for action_prefix in ("Executing action ", "Workflow moved to action ")
            if message.startswith(action_prefix)
        }
        if action_ids:
            current_action_id = next(iter(action_ids)) if len(action_ids) == 1 else None
        if any(
            message.startswith("Executing action ")
            or message.startswith("Workflow moved to action ")
            or message == "Workflow completed"
            or "Errored:" in message
            for message in messages
        ):
            resume_at = None
        if pauses:
            resume_at = None
        if (
            current_action_id in delay_action_ids
            and len(pauses) == 1
            and not any(
                message.startswith("Workflow moved to action ")
                or message == "Workflow completed"
                or "Errored:" in message
                for message in messages
            )
        ):
            try:
                parsed = datetime.fromisoformat(pauses[0])
                resume_at = parsed if parsed.tzinfo is not None else None
            except ValueError:
                resume_at = None
    return resume_at if resume_at is not None and resume_at > now else None


def list_account_event_ids(team: Team, external_id: str) -> list[str]:
    event_ids: list[str] = []
    last_uuid = "00000000-0000-0000-0000-000000000000"
    while True:
        events = execute_hogql_query(
            """SELECT uuid FROM events WHERE startsWith(event, '$account_')
            AND properties.account_external_id = {external_id}
            AND uuid > toUUID({last_uuid}) ORDER BY uuid LIMIT 10000""",
            team=team,
            placeholders={"external_id": ast.Constant(value=external_id), "last_uuid": ast.Constant(value=last_uuid)},
            workload=Workload.ONLINE,
        )
        page_ids = [str(row[0]) for row in events.results or []]
        event_ids.extend(page_ids)
        if len(page_ids) < 10000:
            return event_ids
        last_uuid = page_ids[-1]


def list_account_runs(
    *,
    team: Team,
    account_id: str,
    external_id: str | None,
    workflow_ids: set[str],
    user_access_control: "UserAccessControl",
    page: PageRequest,
) -> Page[AccountAutomation]:
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)
    names = get_workflow_names(team_id=team.pk, workflow_ids=workflow_ids)
    if not names:
        return Page(results=[], count=0)
    event_ids = list_account_event_ids(team, external_id) if external_id is not None else []

    rows = sync_execute(
        """WITH candidates AS (
            SELECT function_id, invocation_id FROM hog_invocation_results
            WHERE team_id = %(team_id)s AND function_kind = 'hog_flow'
                AND function_id IN %(workflow_ids)s AND scheduled_at >= %(after)s
                AND (distinct_id IN %(identities)s OR event_uuid IN %(event_ids)s)
        )
        SELECT function_id, invocation_id,
            argMax(tuple(status, first_scheduled_at, is_deleted, invocation_globals, event_uuid, parent_run_id), version) AS latest
        FROM hog_invocation_results
        WHERE team_id = %(team_id)s AND function_kind = 'hog_flow'
            AND function_id IN %(workflow_ids)s
            AND (function_id, invocation_id) IN candidates
        GROUP BY function_id, invocation_id""",
        {
            "team_id": team.pk,
            "workflow_ids": list(names),
            "after": timezone.now() - timedelta(days=30),
            "identities": [f"account:{account_id}"] + ([external_id] if external_id is not None else []),
            "event_ids": event_ids,
        },
        workload=Workload.ONLINE,
        team_id=team.pk,
    )
    runs: list[AccountAutomation] = []
    log_sources: dict[tuple[str, str], str] = {}
    for workflow_id, invocation_id, (status, triggered_at, is_deleted, stored, event_uuid, parent_run_id) in rows:
        run_key = (workflow_id, invocation_id)
        log_sources[run_key] = parent_run_id or workflow_id
        if is_deleted:
            continue
        if event_uuid not in event_ids and not matches_account(decode_run_context(stored), account_id, external_id):
            continue
        runs.append(
            AccountAutomation(
                workflow_id=workflow_id,
                workflow_name=names[workflow_id],
                invocation_id=invocation_id,
                status=status,
                triggered_at=triggered_at.replace(tzinfo=UTC),
                last_completed_step_at=None,
                expected_resume_at=None,
            )
        )

    ordered = sorted(runs, key=lambda run: (run.triggered_at, run.invocation_id), reverse=True)
    selected = ordered[page.offset : page.offset + page.limit]
    if not selected:
        return Page(results=[], count=len(ordered))
    logs = sync_execute(
        """SELECT log_source_id, instance_id, timestamp, message FROM log_entries
        WHERE team_id = %(team_id)s AND log_source = 'hog_flow'
            AND (log_source_id, instance_id) IN %(run_keys)s
            AND timestamp >= %(after)s ORDER BY timestamp""",
        {
            "team_id": team.pk,
            "run_keys": [(log_sources[(r.workflow_id, r.invocation_id)], r.invocation_id) for r in selected],
            "after": timezone.now() - timedelta(days=90),
        },
        workload=Workload.ONLINE,
        team_id=team.pk,
    )
    by_run: dict[tuple[str, str], list[tuple[datetime, str]]] = {}
    for workflow_id, invocation_id, timestamp, message in logs:
        by_run.setdefault((workflow_id, invocation_id), []).append((timestamp.replace(tzinfo=UTC), message))
    results = []
    workflows = {
        workflow_id: get_workflow(
            team_id=team.pk, workflow_id=workflow_id, user_access_control=user_access_control, required_level="viewer"
        )
        for workflow_id in {run.workflow_id for run in selected}
    }
    for run in selected:
        workflow_actions = workflows[run.workflow_id].actions
        actions = workflow_actions if isinstance(workflow_actions, list) else []
        run_logs = by_run.get((log_sources[(run.workflow_id, run.invocation_id)], run.invocation_id), [])
        completed_step = get_last_completed_step(
            run_logs,
            exit_action_ids={action["id"] for action in actions if action.get("type") == "exit"},
        )
        step_name = next(
            (action.get("name") for action in actions if completed_step and action["id"] == completed_step.action_id),
            None,
        )
        results.append(
            replace(
                run,
                last_completed_step_at=completed_step.completed_at if completed_step else None,
                last_completed_step_name=step_name or None,
                expected_resume_at=(
                    get_expected_resume_at(
                        run_logs,
                        now=timezone.now(),
                        delay_action_ids={
                            action["id"] for action in actions if action.get("type") in {"delay", "delay_until"}
                        },
                    )
                    if run.status == "running"
                    else None
                ),
            )
        )
    return Page(results=results, count=len(ordered))
