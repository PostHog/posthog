import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import cohere
import posthoganalytics
import temporalio.activity
import temporalio.common
import temporalio.exceptions
import temporalio.workflow
from django.db.models import F, Q

from ee.hogai.summarizers.chains import abatch_summarize_actions
from posthog.models import Action, FeatureFlag
from posthog.models.ai.pg_embeddings import INSERT_BULK_PG_EMBEDDINGS_SQL
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.utils import get_scheduled_start_time


async def _get_orgs_from_the_feature_flag() -> list[str]:
    feature_flag = await FeatureFlag.objects.filter(key="max-rag", team_id=1).afirst()
    if not feature_flag:
        return []
    payload = feature_flag.get_payload("true")
    try:
        orgs = json.loads(payload)["organizations"]
        if isinstance(orgs, list):
            return orgs
    except:
        pass
    return []


async def get_actions_qs(start_dt: datetime, offset: int | None = None, batch_size: int | None = None):
    orgs = await _get_orgs_from_the_feature_flag()
    actions_to_summarize = Action.objects.filter(
        Q(team__organization__in=orgs)
        & Q(updated_at__lte=start_dt)
        & (
            # Never summarized actions
            Q(last_summarized_at__isnull=True)
            # Actions updated after last summarization workflow
            | Q(updated_at__gte=F("last_summarized_at"))
            # Actions updated during this sync to preserve order
            | Q(last_summarized_at=start_dt)
        )
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


def get_cohere_client() -> cohere.AsyncClientV2:
    return cohere.AsyncClientV2()


@dataclass
class RetrieveActionsInputs:
    offset: int
    batch_size: int
    start_dt: str


@temporalio.activity.defn
async def batch_summarize_and_embed_actions(inputs: RetrieveActionsInputs):
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

    cohere_client = get_cohere_client()
    embeddings_response = await cohere_client.embed(
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


@dataclass
class SyncActionVectorsForTeamInputs:
    batch_size: int
    start_dt: str


@dataclass
class SyncActionVectorsForTeamOutputs:
    has_more: bool


@temporalio.activity.defn
async def sync_action_vectors_for_team(inputs: SyncActionVectorsForTeamInputs) -> SyncActionVectorsForTeamOutputs:
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)
    actions_to_sync = (
        Action.objects.filter(
            Q(last_summarized_at__lte=workflow_start_dt)
            & (
                Q(last_summarized_at__gte=F("embedding_last_synced_at"))
                | (Q(embedding_last_synced_at__isnull=True) & Q(last_summarized_at__isnull=False))
            )
        )
        .order_by("id", "team_id", "updated_at")
        .values("team_id", "id", "embedding", "summary", "name", "description", "deleted")
    )

    batch = [
        (
            "action",
            action["team_id"],
            action["id"],
            action["embedding"],
            action["summary"],
            json.dumps({"name": action["name"], "description": action["description"]}),
            1 if action["deleted"] else 0,
        )
        async for action in actions_to_sync
    ]

    if not batch:
        return SyncActionVectorsForTeamOutputs(has_more=False)

    async with get_client() as client:
        await client.execute_query(
            INSERT_BULK_PG_EMBEDDINGS_SQL,
            *batch,
        )

    bulk_update = [
        Action(id=action["id"], embedding_last_synced_at=workflow_start_dt) async for action in actions_to_sync
    ]
    await Action.objects.abulk_update(bulk_update, ["embedding_last_synced_at"])

    return SyncActionVectorsForTeamOutputs(has_more=len(batch) == inputs.batch_size)


@dataclass
class SyncVectorsInputs:
    start_dt: datetime | None = None
    batch_size: int = 96
    max_parallel_requests: int = 4
    sync_batch_size: int = 50000


@temporalio.workflow.defn(name="ai-sync-vectors")
class SyncVectorsWorkflow(PostHogWorkflow):
    _updated_actions: set[int]

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
            retry_policy=temporalio.common.RetryPolicy(initial_interval=timedelta(seconds=30), maximum_attempts=3),
        )

        tasks = []
        for i in range(0, approximate_count, inputs.batch_size):
            tasks.append(
                temporalio.workflow.execute_activity(
                    batch_summarize_and_embed_actions,
                    RetrieveActionsInputs(i, inputs.batch_size, start_dt_str),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(
                        initial_interval=timedelta(seconds=30), maximum_attempts=3
                    ),
                )
            )

            # Maximum alllowed parallel request count to LLMs is 384 (96 * 4).
            if len(tasks) == inputs.max_parallel_requests:
                await asyncio.gather(*tasks)
                tasks = []

        if tasks:
            await asyncio.gather(*tasks)

        while True:
            res = await temporalio.workflow.execute_activity(
                sync_action_vectors_for_team,
                SyncActionVectorsForTeamInputs(inputs.batch_size, start_dt_str),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(initial_interval=timedelta(seconds=30), maximum_attempts=3),
            )
            if not res.has_more:
                break
