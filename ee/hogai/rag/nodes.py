import xml.etree.ElementTree as ET
from typing import Literal

from cohere.core.api_error import ApiError as BaseCohereApiError
from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql_queries.ai.pg_embeddings_query_runner import PgEmbeddingsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action
from posthog.schema import PgEmbeddingsQuery

from .utils import get_cohere_client


class ProductAnalyticsRetriever(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        plan = state.root_tool_insight_plan
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
        return PartialAssistantState(rag_context=self._retrieve_actions(response.embeddings.float_[0]))

    def router(self, state: AssistantState) -> Literal["trends", "funnel", "retention", "end"]:
        return state.root_tool_insight_type or "end"

    def _retrieve_actions(self, embedding: list[float]) -> str:
        runner = PgEmbeddingsQueryRunner(
            team=self._team,
            query=PgEmbeddingsQuery(embedding=embedding),
        )
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        actions = Action.objects.filter(team=self._team, id__in=[row.id for row in response.results])

        root = ET.Element("defined_actions")
        for action in actions:
            action_tag = ET.SubElement(root, "action")
            name_tag = ET.SubElement(action_tag, "name")
            name_tag.text = action.name

            if description := action.description:
                desc_tag = ET.SubElement(action_tag, "description")
                desc_tag.text = description

        return ET.tostring(root, encoding="unicode")
