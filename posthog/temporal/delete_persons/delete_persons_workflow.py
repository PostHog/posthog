import json
import typing
import asyncio
import datetime as dt
import itertools
import dataclasses

import temporalio.common
import temporalio.activity
import temporalio.workflow
from structlog import get_logger

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

LOGGER = get_logger(__name__)

# Personhog RPC request caps (see proto/personhog/types/v1/person.proto).
GET_PERSONS_MAX_IDS = 250
DELETE_PERSONS_MAX_UUIDS = 1000


def _chunked(items: list, size: int) -> typing.Iterator[list]:
    it = iter(items)
    while chunk := list(itertools.islice(it, size)):
        yield chunk


def _delete_specific_persons_via_personhog(team_id: int, person_ids: list[int]) -> int:
    """Delete specific persons by id via personhog.

    Resolves ids -> uuids with GetPersons (capped at 250/call) and deletes with
    DeletePersons (capped at 1000/call). DeletePersons cascades the per-person
    cohortpeople cleanup, so no separate cohort delete is needed here.
    """
    from posthog.personhog_client.caller_tag import personhog_caller_tag
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import DeletePersonsRequest, GetPersonsRequest

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    with personhog_caller_tag("delete-persons/by-ids"):
        uuids: list[str] = []
        for id_chunk in _chunked(person_ids, GET_PERSONS_MAX_IDS):
            persons_resp = client.get_persons(GetPersonsRequest(team_id=team_id, person_ids=id_chunk))
            uuids.extend(person.uuid for person in persons_resp.persons)

        deleted = 0
        for uuid_chunk in _chunked(uuids, DELETE_PERSONS_MAX_UUIDS):
            delete_resp = client.delete_persons(DeletePersonsRequest(team_id=team_id, person_uuids=uuid_chunk))
            deleted += delete_resp.deleted_count
        return deleted


def _delete_team_persons_batch_via_personhog(team_id: int, batch_size: int) -> int:
    """Delete up to `batch_size` of a team's persons via personhog, returning the count."""
    from posthog.personhog_client.caller_tag import personhog_caller_tag
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import DeletePersonsBatchForTeamRequest

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    with personhog_caller_tag("delete-persons/by-team"):
        resp = client.delete_persons_batch_for_team(
            DeletePersonsBatchForTeamRequest(team_id=team_id, batch_size=batch_size)
        )
        return resp.deleted_count


@dataclasses.dataclass
class PrecleanCohortMembersActivityInputs:
    """Inputs for the `preclean_cohort_members_activity`."""

    team_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_id": self.team_id}


@temporalio.activity.defn
async def preclean_cohort_members_activity(inputs: PrecleanCohortMembersActivityInputs) -> None:
    """Whole-team mode: clear the team's cohort memberships by cohort before deleting persons.

    posthog_cohortpeople has no FK to posthog_person, so it must be cleared explicitly.
    For a whole-team delete we use the existing by-cohort RPC path (the same one the
    team-teardown flow uses); the per-person DeletePersons cascade covers the by-ids mode.
    """
    from django.db import close_old_connections

    from posthog.models.team.util import _delete_cohort_members_for_all_teams

    async with Heartbeater():
        logger = LOGGER.bind(team_id=inputs.team_id)
        await asyncio.to_thread(close_old_connections)
        await asyncio.to_thread(_delete_cohort_members_for_all_teams, [inputs.team_id])
        await logger.ainfo("Cleared cohort memberships for team")


@dataclasses.dataclass
class DeletePersonsActivityInputs:
    """Inputs for the `delete_persons_activity`."""

    team_id: int
    person_ids: list[int] = dataclasses.field(default_factory=list)
    batch_number: int = 0
    batches: int = 1
    batch_size: int = 1000

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "batch_size": self.batch_size,
            "batch_number": self.batch_number,
            "batches": self.batches,
        }


@temporalio.activity.defn
async def delete_persons_activity(inputs: DeletePersonsActivityInputs) -> tuple[int, bool]:
    """Delete one batch of persons via personhog, returning (deleted_count, should_continue)."""
    async with Heartbeater():
        logger = LOGGER.bind()
        logger.info("Deleting batch %d of %d", inputs.batch_number, inputs.batches)

        if inputs.person_ids:
            # Specific persons: process this batch's slice of the id list.
            start = inputs.batch_number * inputs.batch_size
            id_slice = inputs.person_ids[start : start + inputs.batch_size]
            if not id_slice:
                return 0, False
            deleted = await asyncio.to_thread(_delete_specific_persons_via_personhog, inputs.team_id, id_slice)
            should_continue = start + inputs.batch_size < len(inputs.person_ids)
        else:
            # Whole team: delete up to batch_size and keep going until a batch is short.
            deleted = await asyncio.to_thread(
                _delete_team_persons_batch_via_personhog, inputs.team_id, inputs.batch_size
            )
            should_continue = deleted >= inputs.batch_size

        logger.info("Deleted %d persons", deleted)
        return deleted, should_continue


@dataclasses.dataclass
class DeletePersonsWorkflowInputs:
    """Inputs for the `DeletePersonsWorkflow`."""

    team_id: int
    person_ids: list[int] = dataclasses.field(default_factory=list)
    batches: int = 1
    batch_size: int = 1000

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "batch_size": self.batch_size,
            "batches": self.batches,
        }


@temporalio.workflow.defn(name="delete-persons")
class DeletePersonsWorkflow(PostHogWorkflow):
    """Workflow to delete persons and their dependent rows from the persons database via personhog.

    All deletion goes through personhog RPCs (no direct database connection). For a
    whole-team delete, cohort memberships are cleared up front by cohort and persons are
    then removed in batches; for a delete scoped to specific person_ids, GetPersons +
    DeletePersons handle persons, distinct_ids, and per-person cohort memberships together.
    """

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.paused = False
        self.confirmed = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DeletePersonsWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return DeletePersonsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: DeletePersonsWorkflowInputs):
        """Run all batches to delete persons.

        We wait for a confirmation signal before deleting anything. Before each batch we
        check the `paused` flag and halt until it is toggled off again.
        """
        await temporalio.workflow.wait_condition(lambda: self.confirmed)

        # Whole-team deletes clear cohort memberships by cohort up front; the by-ids path
        # relies on the per-person DeletePersons cascade instead.
        if not inputs.person_ids:
            await temporalio.workflow.execute_activity(
                preclean_cohort_members_activity,
                PrecleanCohortMembersActivityInputs(team_id=inputs.team_id),
                heartbeat_timeout=dt.timedelta(seconds=30),
                start_to_close_timeout=dt.timedelta(hours=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=360),
                    maximum_attempts=0,
                    non_retryable_error_types=[],
                ),
            )

        for batch_number in range(0, inputs.batches):
            await temporalio.workflow.wait_condition(lambda: not self.paused)

            delete_persons_activity_inputs = DeletePersonsActivityInputs(
                team_id=inputs.team_id,
                person_ids=inputs.person_ids,
                batch_number=batch_number,
                batches=inputs.batches,
                batch_size=inputs.batch_size,
            )

            _, should_continue = await temporalio.workflow.execute_activity(
                delete_persons_activity,
                delete_persons_activity_inputs,
                heartbeat_timeout=dt.timedelta(seconds=30),
                start_to_close_timeout=dt.timedelta(hours=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=360),
                    maximum_attempts=0,
                    non_retryable_error_types=[],
                ),
            )

            if not should_continue:
                break

    @temporalio.workflow.signal
    async def confirm(self) -> None:
        """Signal handler for workflow confirmation to start."""
        async with self.lock:
            self.confirmed = True

    @temporalio.workflow.update
    async def pause(self) -> None:
        """Signal handler for workflow to pause or unpause."""
        async with self.lock:
            self.paused = not self.paused
