import json
import xml.etree.ElementTree as ET
from typing import Any, Literal, cast

import posthoganalytics
from cohere.core.api_error import ApiError as BaseCohereApiError
from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.embeddings import get_cohere_client
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.ai.vector_search_query_runner import VectorSearchQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action
from posthog.schema import CachedVectorSearchQueryResponse, TeamTaxonomyQuery, VectorSearchQuery

NextRagNode = Literal["trends", "funnel", "retention", "end"]


class ProductAnalyticsRetriever(AssistantNode):
    """
    Injects product analytics context: actions and events.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        configurable = config.get("configurable", {})
        trace_id = configurable.get("trace_id")
        distinct_id = configurable.get("distinct_id")

        plan = state.root_tool_insight_plan
        if not plan:
            return None

        # Kick off retrieval of the event taxonomy.
        self._prewarm_queries()

        try:
            response = get_cohere_client().embed(
                texts=[plan],
                input_type="search_query",
                model="embed-english-v3.0",
                embedding_types=["float"],
            )
        except BaseCohereApiError:
            return None
        if not response.embeddings.float_:
            return None
        return PartialAssistantState(
            rag_context=self._retrieve_actions(
                response.embeddings.float_[0], trace_id=trace_id, distinct_id=distinct_id
            )
        )

    def router(self, state: AssistantState) -> NextRagNode:
        next_node = cast(NextRagNode, state.root_tool_insight_type or "end")
        return next_node

    def _retrieve_actions(
        self, embedding: list[float], trace_id: Any | None = None, distinct_id: Any | None = None
    ) -> str:
        runner = VectorSearchQueryRunner(
            team=self._team,
            query=VectorSearchQuery(embedding=embedding),
        )
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not isinstance(response, CachedVectorSearchQueryResponse):
            return ""

        actions = Action.objects.filter(team=self._team, id__in=[row.id for row in response.results])

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

        distances = [row.distance for row in response.results]
        self._report_metrics(distances, trace_id, distinct_id)

        return ET.tostring(root, encoding="unicode")

    def _prewarm_queries(self):
        """
        Since this node is already blocking, we can pre-warm the taxonomy queries to avoid further delays.
        This will slightly reduce latency.
        """
        TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
        )

    def _report_metrics(self, distances: list[float], trace_id: Any | None, distinct_id: Any | None):
        if not trace_id or not distinct_id:
            return
        metrics = {
            "actions_avg_distance": sum(distances) / len(distances),
            "actions_med_distance": sorted(distances)[len(distances) // 2],
            "actions_distances": json.dumps(distances),
        }
        for metric_name, metric_value in metrics.items():
            posthoganalytics.capture(
                distinct_id,
                "$ai_metric",
                {
                    "$ai_trace_id": trace_id,
                    "$ai_metric_name": metric_name,
                    "$ai_metric_value": metric_value,
                },
            )
