import logging

import pytest

from braintrust import EvalCase, Score
from braintrust_core.score import Scorer
from deepdiff import DeepDiff

from posthog.schema import (
    PropertyOperator,
    RevenueAnalyticsAssistantFilters,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsPropertyFilter,
)

from products.revenue_analytics.backend.max_tools import RevenueAnalyticsFilterOptionsGraph
from products.revenue_analytics.backend.prompts import USER_FILTER_OPTIONS_PROMPT

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.models.assistant import Conversation

from ...base import MaxPublicEval

logger = logging.getLogger(__name__)

DUMMY_CURRENT_FILTERS = RevenueAnalyticsAssistantFilters(
    date_from="-3m",
    date_to=None,
    breakdown=[],
    properties=[
        RevenueAnalyticsPropertyFilter(
            key="revenue_analytics_customer.country",
            type="revenue_analytics",
            value=["US"],
            operator=PropertyOperator.EXACT,
        ),
    ],
)


@pytest.fixture
def call_filter_revenue_analytics(demo_org_team_user):
    graph = RevenueAnalyticsFilterOptionsGraph(
        demo_org_team_user[1], demo_org_team_user[2], tool_call_id="test-tool-call-id"
    ).compile_full_graph(checkpointer=DjangoCheckpointer())

    async def callable(change: str) -> dict:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

        # Convert filters to JSON string and use test-specific prompt
        filters_json = DUMMY_CURRENT_FILTERS.model_dump_json(indent=2)

        graph_input = {
            "change": USER_FILTER_OPTIONS_PROMPT.format(change=change, current_filters=filters_json),
            "output": None,
        }

        result = await graph.ainvoke(graph_input, config={"configurable": {"thread_id": conversation.id}})
        return result

    return callable


class FilterGenerationCorrectness(Scorer):
    """Score the correctness of generated filters."""

    def _name(self):
        return "filter_generation_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        try:
            actual_filters = RevenueAnalyticsAssistantFilters.model_validate(output["output"])
        except Exception as e:
            logger.exception(f"Error parsing filters: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid filter structure"})

        # Convert both objects to dict for deepdiff comparison
        actual_dict = actual_filters.model_dump()
        expected_dict = expected.model_dump()

        # Use deepdiff to find differences
        diff = DeepDiff(expected_dict, actual_dict, ignore_order=True, report_repetition=True)

        if not diff:
            return Score(name=self._name(), score=1.0, metadata={"reason": "Perfect match"})

        # Calculate score based on number of differences
        total_fields = len(expected_dict.keys())
        changed_fields = (
            len(diff.get("values_changed", {}))
            + len(diff.get("dictionary_item_added", set()))
            + len(diff.get("dictionary_item_removed", set()))
        )

        score = max(0.0, (total_fields - changed_fields) / total_fields)

        return Score(
            name=self._name(),
            score=score,
            metadata={
                "differences": str(diff),
                "total_fields": total_fields,
                "changed_fields": changed_fields,
                "reason": f"Found {changed_fields} differences out of {total_fields} fields",
            },
        )


class AskUserForHelp(Scorer):
    """Score the correctness of the ask_user_for_help tool."""

    def _name(self):
        return "ask_user_for_help_scorer"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if "output" not in output or output["output"] is None:
            if (
                "intermediate_steps" in output
                and len(output["intermediate_steps"]) > 0
                and output["intermediate_steps"][-1][0].tool == "ask_user_for_help"
            ):
                return Score(
                    name=self._name(), score=1, metadata={"reason": "LLM returned valid ask_user_for_help response"}
                )
            else:
                return Score(
                    name=self._name(),
                    score=0,
                    metadata={"reason": "LLM did not return valid ask_user_for_help response"},
                )
        else:
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned a filter"})


class DateTimeFilteringCorrectness(Scorer):
    """Score the correctness of the date time filtering."""

    def _name(self):
        return "date_time_filtering_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        try:
            actual_filters = RevenueAnalyticsAssistantFilters.model_validate(output["output"])
        except Exception as e:
            logger.exception(f"Error parsing filters: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid filter structure"})

        if actual_filters.date_from == expected.date_from and actual_filters.date_to == expected.date_to:
            return Score(name=self._name(), score=1.0, metadata={"reason": "LLM returned valid date time filters"})
        elif actual_filters.date_from == expected.date_from:
            return Score(
                name=self._name(),
                score=0.5,
                metadata={"reason": "LLM returned valid date_from but did not return valid date_to"},
            )
        elif actual_filters.date_to == expected.date_to:
            return Score(
                name=self._name(),
                score=0.5,
                metadata={"reason": "LLM returned valid date_to but did not return valid date_from"},
            )
        else:
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid date time filters"})


@pytest.mark.django_db
async def eval_tool_filter_revenue_analytics(call_filter_revenue_analytics, pytestconfig):
    await MaxPublicEval(
        experiment_name="tool_filter_revenue_analytics",
        task=call_filter_revenue_analytics,
        scores=[FilterGenerationCorrectness(), DateTimeFilteringCorrectness()],
        data=[
            # Test date range filtering
            EvalCase(
                input="show me my MRR in the last 3 months",
                expected=RevenueAnalyticsAssistantFilters(date_from="-3m", date_to=None, properties=[], breakdown=[]),
            ),
            # Test location filtering
            EvalCase(
                input="Show me my MRR for users located in the US",
                expected=RevenueAnalyticsAssistantFilters(
                    date_from="-3m",
                    date_to=None,
                    breakdown=[],
                    properties=[
                        RevenueAnalyticsPropertyFilter(
                            key="revenue_analytics_customer.country",
                            type="revenue_analytics",
                            value=["US"],
                            operator=PropertyOperator.EXACT,
                        )
                    ],
                ),
            ),
            # Test filter combination
            EvalCase(
                input="Show me my MRR in the last 3 months for users located in the US for the 'Pro' plan",
                expected=RevenueAnalyticsAssistantFilters(
                    date_from="-3m",
                    date_to=None,
                    breakdown=[],
                    properties=[
                        RevenueAnalyticsPropertyFilter(
                            key="revenue_analytics_customer.country",
                            type="revenue_analytics",
                            value=["US"],
                            operator=PropertyOperator.EXACT,
                        ),
                        RevenueAnalyticsPropertyFilter(
                            key="revenue_analytics_product.name",
                            type="revenue_analytics",
                            value=["Pro"],
                            operator=PropertyOperator.ICONTAINS,
                        ),
                    ],
                ),
            ),
            # Test breakdown filtering
            EvalCase(
                input="What's my growth per product?",
                expected=RevenueAnalyticsAssistantFilters(
                    date_from="-3m",
                    date_to=None,
                    properties=[],
                    breakdown=[
                        RevenueAnalyticsBreakdown(property="revenue_analytics_product.name", type="revenue_analytics")
                    ],
                ),
            ),
            # Comprehensive filter combination
            EvalCase(
                input="Show me my revenue in 2023 split by product for those in Austria",
                expected=RevenueAnalyticsAssistantFilters(
                    date_from="2023-01-01T00:00:00:000",
                    date_to="2023-12-31T23:59:59:999",
                    properties=[
                        RevenueAnalyticsPropertyFilter(
                            key="revenue_analytics_customer.country",
                            type="revenue_analytics",
                            value=["AT"],
                            operator=PropertyOperator.EXACT,
                        ),
                    ],
                    breakdown=[
                        RevenueAnalyticsBreakdown(property="revenue_analytics_product.name", type="revenue_analytics")
                    ],
                ),
            ),
            # Test time-based filtering
            EvalCase(
                input="Assuming we're in 2023, show me my MRR data since the 1st of August",
                expected=DUMMY_CURRENT_FILTERS.model_copy(update={"date_from": "2023-08-01T00:00:00:000"}),
            ),
            EvalCase(
                input="Assuming we're in 2023, show me my revenue in September",
                expected=DUMMY_CURRENT_FILTERS.model_copy(
                    update={"date_from": "2023-09-01T00:00:00:000", "date_to": "2023-09-30T23:59:59:999"}
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_tool_filter_revenue_analytics_ask_user_for_help(call_filter_revenue_analytics, pytestconfig):
    await MaxPublicEval(
        experiment_name="tool_filter_revenue_analytics_ask_user_for_help",
        task=call_filter_revenue_analytics,
        scores=[AskUserForHelp()],
        data=[EvalCase(input="Show me my MRR", expected="clarify")],
        pytestconfig=pytestconfig,
    )
