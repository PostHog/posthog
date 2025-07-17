import json
import xml.etree.ElementTree as ET
from typing import Any, Literal

import posthoganalytics
from azure.core.exceptions import HttpResponseError as AzureHttpResponseError
from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.embeddings import embed_search_query, get_azure_embeddings_client
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.ai.vector_search_query_runner import (
    LATEST_ACTIONS_EMBEDDING_VERSION,
    VectorSearchQueryRunner,
)
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action
from posthog.schema import MaxActionContext, CachedVectorSearchQueryResponse, TeamTaxonomyQuery, VectorSearchQuery

from ..base import AssistantNode

NEXT_RAG_NODES = ["trends", "funnel", "retention", "sql", "end"]
NextRagNode = Literal["trends", "funnel", "retention", "sql", "end"]


class InsightRagContextNode(AssistantNode):
    """
    Injects the RAG context of product analytics insights: actions and events.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        trace_id = self._get_trace_id(config)
        distinct_id = self._get_user_distinct_id(config)

        plan = state.root_tool_insight_plan
        if not plan:
            return None

        # Kick off retrieval of the event taxonomy.
        self._prewarm_queries()

        actions_in_context = []
        if ui_context := self._get_ui_context(state):
            actions_in_context = ui_context.actions if ui_context.actions else []

        try:
            embeddings_client = get_azure_embeddings_client()
            vector = embed_search_query(embeddings_client, plan)
        except (AzureHttpResponseError, ValueError) as e:
            posthoganalytics.capture_exception(e, distinct_id=distinct_id, properties={"tag": "max"})
            if len(actions_in_context) == 0:
                return None
            else:
                vector = None
        return PartialAssistantState(
            rag_context=self._retrieve_actions(
                vector, actions_in_context=actions_in_context, trace_id=trace_id, distinct_id=distinct_id
            )
        )

    def _retrieve_actions(
        self,
        embedding: list[float] | None,
        actions_in_context: list[MaxActionContext],
        trace_id: Any | None = None,
        distinct_id: Any | None = None,
    ) -> str:
        # action.id in UI context actions is typed as float from schema.py, so we need to convert it to int to match the Action.id field
        ids = [str(int(action.id)) for action in actions_in_context] if actions_in_context else []

        if embedding:
            runner = VectorSearchQueryRunner(
                team=self._team,
                query=VectorSearchQuery(embedding=embedding, embeddingVersion=LATEST_ACTIONS_EMBEDDING_VERSION),
            )
            response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
            if isinstance(response, CachedVectorSearchQueryResponse) and response.results:
                ids = list({row.id for row in response.results} | set(ids))
                distances = [row.distance for row in response.results]
                self._report_metrics(distances, trace_id, distinct_id)

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

    def _prewarm_queries(self):
        """
        Since this node is already blocking, we can pre-warm the taxonomy queries to avoid further delays.
        This will slightly reduce latency.
        """
        TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
        )

    def _report_metrics(self, distances: list[float], trace_id: Any | None, distinct_id: Any | None):
        if not trace_id or not distinct_id or not distances:
            return
        metrics = {
            "actions_avg_distance": sum(distances) / len(distances),
            "actions_med_distance": sorted(distances)[len(distances) // 2],
            "actions_distances": json.dumps(distances),
        }
        for metric_name, metric_value in metrics.items():
            posthoganalytics.capture(
                "$ai_metric",
                distinct_id=distinct_id,
                properties={
                    "$ai_trace_id": trace_id,
                    "$ai_metric_name": metric_name,
                    "$ai_metric_value": metric_value,
                },
            )
