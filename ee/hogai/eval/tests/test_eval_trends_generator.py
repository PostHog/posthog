from typing import cast

from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.utils import EvalBaseTest
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import AssistantTrendsQuery, HumanMessage, VisualizationMessage


class TestEvalTrendsGenerator(EvalBaseTest):
    def _call_node(self, query: str, plan: str) -> AssistantTrendsQuery:
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)
            .add_trends_generator(AssistantNodeName.END)
            .compile()
        )
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)], plan=plan),
            self._get_config(),
        )
        return cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1]).answer

    def test_node_replaces_equals_with_contains(self):
        query = "what is pageview trend for users with name John?"
        plan = """Events:
        - $pageview
            - math operation: total count
            - property filter 1
                - person
                - name
                - equals
                - John
        """
        actual_output = self._call_node(query, plan).model_dump_json(exclude_none=True)
        assert "exact" not in actual_output
        assert "icontains" in actual_output
        assert "John" not in actual_output
        assert "john" in actual_output

    def test_node_leans_towards_line_graph(self):
        query = "How often do users download files?"
        # We ideally want to consider both total count of downloads per period, as well as how often a median user downloads
        plan = """Events:
        - downloaded_file
            - math operation: total count
        - downloaded_file
            - math operation: median count per user
        """
        actual_output = self._call_node(query, plan)
        assert actual_output.trendsFilter.display == "ActionsLineGraph"
        assert actual_output.series[0].kind == "EventsNode"
        assert actual_output.series[0].event == "downloaded_file"
        assert actual_output.series[0].math == "total"
        assert actual_output.series[1].kind == "EventsNode"
        assert actual_output.series[1].event == "downloaded_file"
        assert actual_output.series[1].math == "median_count_per_actor"
