from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.utils import EvalBaseTest
from ee.hogai.utils import AssistantNodeName
from posthog.schema import HumanMessage


class TestEvalTrendsPlanner(EvalBaseTest):
    plan_correctness_metric = GEval(
        name="Trends Plan Correctness",
        criteria="You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a trends insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about trends insights.",
        evaluation_steps=[
            "A plan must define at least one event and a math type, but it is not required to define any filters, breakdowns, or formulas.",
            "Compare events, properties, math types, and property values of 'expected output' and 'actual output'.",
            "Check if the combination of events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.",
            # The criteria for aggregations must be more specific because there isn't a way to bypass them.
            "Check if the math types in 'actual output' match those in 'expected output.' If the aggregation type is specified by a property, user, or group in 'expected output', the same property, user, or group must be used in 'actual output'.",
            "If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.",
            "If 'expected output' contains a formula, check if 'actual output' contains a similar formula, and heavily penalize if the formula is not present or different.",
            # We don't want to see in the output unnecessary property filters. The assistant tries to use them all the time.
            "Heavily penalize if the 'actual output' contains any excessive output not present in the 'expected output'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.EXPECTED_OUTPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.7,
    )

    def _call_node(self, query):
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
            .add_trends_planner(AssistantNodeName.END)
            .compile()
        )
        state = graph.invoke({"messages": [HumanMessage(content=query)]})
        return state["plan"]

    def test_no_excessive_property_filters(self):
        query = "Show the $pageview trend"
        test_case = LLMTestCase(
            input=query,
            expected_output="""
            Events:
            - $pageview
                - math operation: total count
            """,
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [self.plan_correctness_metric])

    def test_no_excessive_property_filters_for_a_defined_math_type(self):
        query = "What is the MAU?"
        test_case = LLMTestCase(
            input=query,
            expected_output="""
            Events:
            - $pageview
                - math operation: unique users
            """,
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [self.plan_correctness_metric])

    def test_basic_filtering(self):
        query = "can you compare how many US vs India users uploaded a file in the last 30d?"
        test_case = LLMTestCase(
            input=query,
            expected_output="""
            Events:
            - viewed dashboard
                - math operation: total count
                - property filter 1:
                    - entity: event
                    - property name: $geoip_country_name
                    - property type: String
                    - operator: equals
                    - property value: United States
                - property filter 2:
                    - entity: event
                    - property name: $geoip_country_name
                    - property type: String
                    - operator: equals
                    - property value: India

            Breakdown by:
            - breakdown 1:
                - entity: event
                - property name: $geoip_country_name
            """,
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [self.plan_correctness_metric])

    def test_formula_mode(self):
        query = "i want to see a ratio of identify divided by page views"
        test_case = LLMTestCase(
            input=query,
            expected_output="""
            Events:
            - $identify
                - math operation: unique users
            - $pageview
                - math operation: total count

            Formula:
            `A/B`, where `A` is the unique users of `$identify` and `B` is the total count of `$pageview`
            """,
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [self.plan_correctness_metric])

    def test_math_type_by_a_property(self):
        query = "what is the average session duration?"
        test_case = LLMTestCase(
            input=query,
            expected_output="""
            Events:
            - All Events
                - math operation: average by `$session_duration`
            """,
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [self.plan_correctness_metric])

    def test_math_type_by_a_user(self):
        query = "What is the median page view count for a user?"
        test_case = LLMTestCase(
            input=query,
            expected_output="""
            Events:
            - $pageview
                - math operation: median by users
            """,
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [self.plan_correctness_metric])

    def test_needle_in_a_haystack(self):
        query = "How frequently do people pay for a personal-pro plan?"
        test_case = LLMTestCase(
            input=query,
            expected_output="""
            Events:
            - paid_bill
                - math operation: total count
                - property filter 1:
                    - entity: event
                    - property name: plan
                    - property type: String
                    - operator: contains
                    - property value: personal/pro
            """,
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [self.plan_correctness_metric])
