import asyncio
from collections import defaultdict
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime
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
from posthog.models import Action, Team
from posthog.temporal.common.base import PostHogWorkflow

cohere_client = cohere.ClientV2()


@dataclass
class RetrieveActionsInputs:
    offset: int
    batch_size: int
    start_dt: datetime


@dataclass
class UpdatedAction:
    team_id: int
    action_id: int


def get_actions_qs(start_dt: datetime, offset: int | None = None, batch_size: int | None = None):
    actions_to_summarize = Action.objects.filter(
        (Q(updated_at__gte=F("last_summarized_at")) | Q(last_summarized_at__isnull=True)) & Q(updated_at__lte=start_dt)
    ).order_by("updated_at", "team_id")
    if offset is None or batch_size is None:
        return actions_to_summarize
    return actions_to_summarize[offset : offset + batch_size]


@dataclass
class GetApproximateActionsCountInputs:
    start_dt: datetime


@temporalio.activity.defn
async def get_approximate_actions_count(inputs: GetApproximateActionsCountInputs) -> int:
    return await get_actions_qs(inputs.start_dt).acount()


@temporalio.activity.defn
async def batch_summarize_and_embed_actions(inputs: RetrieveActionsInputs) -> list[UpdatedAction]:
    actions_to_summarize = get_actions_qs(inputs.start_dt, inputs.offset, inputs.batch_size)
    actions = [action async for action in actions_to_summarize]

    summaries = await abatch_summarize_actions(actions)
    models_to_update = []
    for action, maybe_summary in zip(actions, summaries):
        if isinstance(maybe_summary, BaseException):
            posthoganalytics.capture_exception(maybe_summary, context={"action_id": action.id})
            continue
        action.last_summarized_at = inputs.start_dt
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

    ns = tpuf.Namespace(f"project:{team.id}")
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
    start_dt: datetime = field(default_factory=datetime.now)
    batch_size: int = 96
    max_parallel_requests: int = 4
    sync_batch_size: int = 2000  # Maximum available is 5k/namespace/s
    max_parallel_sync_requests: int = 10  # Maximum available is 200k documents/s


@temporalio.workflow.defn(name="ai-sync-vectors")
class SyncVectors(PostHogWorkflow):
    _updated_actions_by_team: defaultdict[int, set[int]]

    def __init__(self):
        self._updated_actions_by_team = defaultdict(set)

    @temporalio.workflow.run
    async def run(self, inputs: SyncVectorsInputs):
        approximate_count = await temporalio.workflow.execute_activity(
            get_approximate_actions_count,
            GetApproximateActionsCountInputs(inputs.start_dt),
        )
        if not approximate_count:
            return

        tasks: list[Coroutine[Any, Any, list[UpdatedAction]]] = []
        for i in range(0, approximate_count, inputs.batch_size):
            tasks.append(
                temporalio.workflow.execute_activity(
                    batch_summarize_and_embed_actions,
                    RetrieveActionsInputs(i, inputs.batch_size, inputs.start_dt),
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
            for batch in range(0, len(action_ids), inputs.sync_batch_size):
                batch_action_ids = list(action_ids)[batch : batch + inputs.sync_batch_size]
                tasks.append(
                    temporalio.workflow.execute_activity(
                        sync_action_vectors_for_team,
                        SyncActionVectorsForTeamInputs(team_id, batch_action_ids),
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
