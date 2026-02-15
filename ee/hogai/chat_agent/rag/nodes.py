import json
import time

# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (XML generation only, no parsing - no XXE risk)
import xml.etree.ElementTree as ET
from typing import Literal, TypedDict

import posthoganalytics
from azure.core.exceptions import HttpResponseError as AzureHttpResponseError
from langchain_core.runnables import RunnableConfig, RunnableLambda
from prometheus_client import Histogram

from posthog.schema import CachedVectorSearchQueryResponse, MaxActionContext, TeamTaxonomyQuery, VectorSearchQuery

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.event_usage import report_user_action
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.ai.vector_search_query_runner import (
    LATEST_ACTIONS_EMBEDDING_VERSION,
    VectorSearchQueryRunner,
)
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action

from ee.hogai.core.node import AssistantNode
from ee.hogai.utils.embeddings import embed_search_query, get_azure_embeddings_client
from ee.hogai.utils.types import AssistantState, PartialAssistantState

NEXT_RAG_NODES = ["trends", "funnel", "retention", "sql", "end"]
NextRagNode = Literal["trends", "funnel", "retention", "sql", "end"]

RAG_EMBEDDING_TIMING_HISTOGRAM = Histogram(
    "posthog_ai_rag_embedding_duration_seconds",
    "Time to generate embeddings for RAG search query",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

RAG_SEARCH_TIMING_HISTOGRAM = Histogram(
    "posthog_ai_rag_search_duration_seconds",
    "Time to search for actions using vector search",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

RAG_RETRIEVE_TIMING_HISTOGRAM = Histogram(
    "posthog_ai_rag_retrieve_duration_seconds",
    "Time to retrieve and format actions from database",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)


class RagContext(TypedDict):
    plan: str
    actions_in_context: list[MaxActionContext]
    embedding: list[float] | None
    action_ids: list[str]


class InsightRagContextNode(AssistantNode):
    """
    Injects the RAG context of product analytics insights: actions and events.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        plan = state.root_tool_insight_plan
        if not plan:
            return None

        # Kick off retrieval of the event taxonomy.
        self._prewarm_queries()

        actions_in_context = []
        if ui_context := self.context_manager.get_ui_context(state):
            actions_in_context = ui_context.actions if ui_context.actions else []

        context: RagContext = {
            "plan": plan,
            "actions_in_context": actions_in_context,
            "embedding": None,
            "action_ids": [],
        }

        # Compose the runnable chain
        chain = (
            RunnableLambda(self._get_embedding)
            | RunnableLambda(self._search_actions)
            | RunnableLambda(self._retrieve_actions)
        )

        rag_context = chain.invoke(context, config)

        if not rag_context:
            return None

        return PartialAssistantState(rag_context=rag_context)

    def _get_embedding(self, context: RagContext, config: RunnableConfig) -> RagContext:
        """Generate embedding for the search query, returns None on error."""
        start_time = time.time()
        try:
            embeddings_client = get_azure_embeddings_client()
            context["embedding"] = embed_search_query(embeddings_client, context["plan"])
        except (AzureHttpResponseError, ValueError) as e:
            posthoganalytics.capture_exception(
                e,
                distinct_id=self._get_user_distinct_id(config),
                properties=self._get_debug_props(config),
            )
            context["embedding"] = None
        finally:
            RAG_EMBEDDING_TIMING_HISTOGRAM.observe(time.time() - start_time)
        return context

    def _search_actions(self, context: RagContext, config: RunnableConfig) -> RagContext:
        """Search for action IDs using vector search and UI context, reports metrics."""
        start_time = time.time()
        try:
            # action.id in UI context actions is typed as float from schema.py, so we need to convert it to int to match the Action.id field
            actions_in_context = context["actions_in_context"]
            embedding = context["embedding"]
            ids = [str(int(action.id)) for action in actions_in_context] if actions_in_context else []

            if embedding:
                runner = VectorSearchQueryRunner(
                    team=self._team,
                    query=VectorSearchQuery(embedding=embedding, embeddingVersion=LATEST_ACTIONS_EMBEDDING_VERSION),
                )
                with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
                    response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
                if isinstance(response, CachedVectorSearchQueryResponse) and response.results:
                    ids = list({row.id for row in response.results} | set(ids))
                    distances = [row.distance for row in response.results]
                    self._report_metrics(config, distances)

            context["action_ids"] = ids
            return context
        finally:
            RAG_SEARCH_TIMING_HISTOGRAM.observe(time.time() - start_time)

    def _retrieve_actions(self, context: RagContext) -> str:
        """Retrieve actions from database and format as XML."""
        start_time = time.time()
        try:
            ids = context["action_ids"]
            if len(ids) == 0:
                return ""

            actions = Action.objects.filter(team__project_id=self._team.project_id, id__in=ids).only(
                "id", "name", "description"
            )

            root = ET.Element("defined_actions")
            for action in actions:
                action_tag = ET.SubElement(root, "action")
                id_tag = ET.SubElement(action_tag, "id")
                id_tag.text = str(action.id)
                name_tag = ET.SubElement(action_tag, "name")
                name_tag.text = action.name

                if description := action.description:
                    desc_tag = ET.SubElement(action_tag, "description")
                    desc_tag.text = description

            return ET.tostring(root, encoding="unicode")
        finally:
            RAG_RETRIEVE_TIMING_HISTOGRAM.observe(time.time() - start_time)

    def _prewarm_queries(self):
        """
        Since this node is already blocking, we can pre-warm the taxonomy queries to avoid further delays.
        This will slightly reduce latency.
        """
        TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
        )

    def _report_metrics(self, config: RunnableConfig, distances: list[float]):
        if not distances:
            return
        metrics = {
            "actions_avg_distance": sum(distances) / len(distances),
            "actions_med_distance": sorted(distances)[len(distances) // 2],
            "actions_distances": json.dumps(distances),
        }
        for metric_name, metric_value in metrics.items():
            report_user_action(
                self._user,
                "$ai_metric",
                properties={
                    **self._get_debug_props(config),
                    "$ai_metric_name": metric_name,
                    "$ai_metric_value": metric_value,
                },
                team=self._team,
            )
