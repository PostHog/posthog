import json
import xml.etree.ElementTree as ET
from typing import Literal

import posthoganalytics
from azure.core.exceptions import HttpResponseError as AzureHttpResponseError
from langchain_core.runnables import RunnableConfig

from posthog.schema import CachedVectorSearchQueryResponse, MaxActionContext, TeamTaxonomyQuery, VectorSearchQuery

from posthog.event_usage import report_user_action
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.ai.vector_search_query_runner import (
    LATEST_ACTIONS_EMBEDDING_VERSION,
    VectorSearchQueryRunner,
)
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action

from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.embeddings import embed_search_query, get_azure_embeddings_client
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

NEXT_RAG_NODES = ["trends", "funnel", "retention", "sql", "end"]
NextRagNode = Literal["trends", "funnel", "retention", "sql", "end"]


class InsightRagContextNode(AssistantNode):
    """
    Injects the RAG context of product analytics insights: actions and events.
    """

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.INSIGHT_RAG_CONTEXT

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        plan = state.root_tool_insight_plan
        if not plan:
            return None

        # Kick off retrieval of the event taxonomy.
        self._prewarm_queries()

        actions_in_context = []
        if ui_context := self.context_manager.get_ui_context(state):
            actions_in_context = ui_context.actions if ui_context.actions else []

        try:
            embeddings_client = get_azure_embeddings_client()
            vector = embed_search_query(embeddings_client, plan)
        except (AzureHttpResponseError, ValueError) as e:
            posthoganalytics.capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            if len(actions_in_context) == 0:
                return None
            else:
                vector = None
        return PartialAssistantState(
            rag_context=self._retrieve_actions(config, vector, actions_in_context=actions_in_context)
        )

    def _retrieve_actions(
        self,
        config: RunnableConfig,
        embedding: list[float] | None,
        actions_in_context: list[MaxActionContext],
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
                self._report_metrics(config, distances)

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
