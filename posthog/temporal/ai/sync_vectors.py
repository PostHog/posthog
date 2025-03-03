import asyncio
import json
from collections import defaultdict
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import cohere
import posthoganalytics
import temporalio.activity
import temporalio.common
import temporalio.exceptions
import temporalio.workflow
import turbopuffer as tpuf
from django.db.models import F, Q

from ee.hogai.summarizers.chains import abatch_summarize_actions
from posthog.models import Action, FeatureFlag, Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.utils import get_scheduled_start_time

cohere_client = cohere.ClientV2()


async def _get_orgs_from_the_feature_flag() -> list[str]:
    feature_flag = await FeatureFlag.objects.filter(key="max-rag", team_id=2).afirst()
    if not feature_flag:
        return []
    payload = feature_flag.get_payload("organizations")
    if not isinstance(payload, list):
        return []
    return payload


async def get_actions_qs(start_dt: datetime, offset: int | None = None, batch_size: int | None = None):
    orgs = await _get_orgs_from_the_feature_flag()
    actions_to_summarize = Action.objects.filter(
        (Q(updated_at__gte=F("last_summarized_at")) | Q(last_summarized_at__isnull=True))
        & Q(updated_at__lte=start_dt)
        & Q(team__organization__in=orgs)
    ).order_by("id", "team_id", "updated_at")
    if offset is None or batch_size is None:
        return actions_to_summarize
    return actions_to_summarize[offset : offset + batch_size]


@dataclass
class GetApproximateActionsCountInputs:
    start_dt: str


@temporalio.activity.defn
async def get_approximate_actions_count(inputs: GetApproximateActionsCountInputs) -> int:
    qs = await get_actions_qs(datetime.fromisoformat(inputs.start_dt))
    return await qs.acount()


@dataclass
class RetrieveActionsInputs:
    offset: int
    batch_size: int
    start_dt: str


@dataclass
class UpdatedAction:
    team_id: int
    action_id: int


@temporalio.activity.defn
async def batch_summarize_and_embed_actions(inputs: RetrieveActionsInputs) -> list[UpdatedAction]:
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)
    actions_to_summarize = await get_actions_qs(workflow_start_dt, inputs.offset, inputs.batch_size)
    actions = [action async for action in actions_to_summarize]

    summaries = await abatch_summarize_actions(actions)
    models_to_update = []
    for action, maybe_summary in zip(actions, summaries):
        if isinstance(maybe_summary, BaseException):
            posthoganalytics.capture_exception(maybe_summary, context={"action_id": action.id})
            continue
        action.last_summarized_at = workflow_start_dt
        action.summary = maybe_summary
        models_to_update.append(action)

    embeddings_response = cohere_client.embed(
        texts=[action.summary for action in models_to_update],
        model="embed-english-v3.0",
        input_type="search_document",
        embedding_types=["float"],
    )
    if not embeddings_response.embeddings.float_:
        raise ValueError("No embeddings found")

    for action, embedding in zip(models_to_update, embeddings_response.embeddings.float_):
        action.embedding = embedding

    await Action.objects.abulk_update(models_to_update, ["embedding", "last_summarized_at", "summary"])
    return [UpdatedAction(team_id=action.team_id, action_id=action.id) for action in models_to_update]


@dataclass
class SyncActionVectorsForTeamInputs:
    team_id: int
    action_ids: list[int]


@temporalio.activity.defn
async def sync_action_vectors_for_team(inputs: SyncActionVectorsForTeamInputs):
    # Verify that the team exists
    team = await Team.objects.aget(id=inputs.team_id)

    models_to_update = [
        action async for action in Action.objects.filter(id__in=inputs.action_ids, team_id=inputs.team_id)
    ]
    if not models_to_update:
        return

    ns = tpuf.Namespace(f"project_{team.id}")
    # Blocking API call
    ns.upsert(
        ids=[action.id for action in models_to_update],
        vectors=[action.embedding for action in models_to_update],
        attributes={
            "name": [action.name for action in models_to_update],
            "description": [action.description for action in models_to_update],
            "domain": ["action"] * len(models_to_update),
            "summary": [action.summary for action in models_to_update],
        },
        distance_metric="cosine_distance",
        schema={
            "name": {
                "type": "string",
                "full_text_search": True,
            },
            "description": {
                "type": "string",
                "full_text_search": True,
            },
            "summary": {
                "type": "string",
                "full_text_search": True,
            },
        },
    )


@dataclass
class SyncVectorsInputs:
    start_dt: datetime | None = None
    batch_size: int = 96
    max_parallel_requests: int = 4
    sync_batch_size: int = 2000  # Maximum available is 5k/namespace/s
    max_parallel_sync_requests: int = 10  # Maximum available is 200k documents/s


@temporalio.workflow.defn(name="ai-sync-vectors")
class SyncVectorsWorkflow(PostHogWorkflow):
    _updated_actions_by_team: defaultdict[int, set[int]]

    def __init__(self):
        self._updated_actions_by_team = defaultdict(set)

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncVectorsInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SyncVectorsInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SyncVectorsInputs):
        start_dt = inputs.start_dt or get_scheduled_start_time()
        start_dt_str = start_dt.isoformat()

        approximate_count = await temporalio.workflow.execute_activity(
            get_approximate_actions_count,
            GetApproximateActionsCountInputs(start_dt_str),
            start_to_close_timeout=timedelta(seconds=15),
        )
        if not approximate_count:
            return

        tasks: list[Coroutine[Any, Any, list[UpdatedAction]]] = []
        for i in range(0, approximate_count, inputs.batch_size):
            tasks.append(
                temporalio.workflow.execute_activity(
                    batch_summarize_and_embed_actions,
                    RetrieveActionsInputs(i, inputs.batch_size, start_dt_str),
                    start_to_close_timeout=timedelta(minutes=5),
                )
            )

            # Maximum alllowed parallel request count to LLMs is 384 (96 * 4).
            if len(tasks) == inputs.max_parallel_requests:
                batches = await asyncio.gather(*tasks)
                tasks = []
                self._update_actions(batches)

        if tasks:
            batches = await asyncio.gather(*tasks)
            self._update_actions(batches)

        tasks: list[Coroutine[Any, Any, None]] = []
        for team_id, action_ids in self._updated_actions_by_team.items():
            sorted_action_ids = sorted(action_ids)  # Deterministic order
            for batch in range(0, len(sorted_action_ids), inputs.sync_batch_size):
                batch_action_ids = sorted_action_ids[batch : batch + inputs.sync_batch_size]
                tasks.append(
                    temporalio.workflow.execute_activity(
                        sync_action_vectors_for_team,
                        SyncActionVectorsForTeamInputs(team_id, batch_action_ids),
                        start_to_close_timeout=timedelta(minutes=1),
                    )
                )

                if len(tasks) == inputs.max_parallel_sync_requests:
                    await asyncio.gather(*tasks)
                    tasks = []

        if tasks:
            await asyncio.gather(*tasks)

    def _update_actions(self, batches: list[list[UpdatedAction]]):
        for actions in batches:
            for action in actions:
                self._updated_actions_by_team[action.team_id].add(action.action_id)
