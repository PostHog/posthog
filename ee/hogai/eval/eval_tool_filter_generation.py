import pytest
import logging
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer

from posthog.schema import (
    MaxRecordingUniversalFilters,
    FilterLogicalOperator,
    RecordingOrder,
    RecordingDurationFilter,
    DurationType,
    PropertyOperator,
    MaxOuterUniversalFiltersGroup,
    MaxInnerUniversalFiltersGroup,
)
from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from ee.models.assistant import Conversation
from .conftest import MaxEval
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.replay.backend.max_tools import (
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_RESPONSE_FORMATS_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
)

logger = logging.getLogger(__name__)

current_filters = {
    "date_from": "-7d",
    "date_to": None,
    "duration": [
        RecordingDurationFilter(key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0)
    ],
    "filter_group": MaxOuterUniversalFiltersGroup(
        type=FilterLogicalOperator.AND_,
        values=[MaxInnerUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[])],
    ),
    "filter_test_accounts": True,
    "order": RecordingOrder.START_TIME,
}


@pytest.fixture
def call_search_session_recordings(demo_org_team_user):
    injected_prompts = {
        "product_description_prompt": PRODUCT_DESCRIPTION_PROMPT,
        "response_formats_prompt": SESSION_REPLAY_RESPONSE_FORMATS_PROMPT,
        "examples_prompt": SESSION_REPLAY_EXAMPLES_PROMPT,
    }
    graph = FilterOptionsGraph(
        demo_org_team_user[1], demo_org_team_user[2], injected_prompts=injected_prompts
    ).compile_full_graph(checkpointer=DjangoCheckpointer())

    async def callable(change: str) -> dict:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

        graph_input = {
            "change": change,
            "generated_filter_options": None,
            "current_filters": current_filters,
        }

        result = await graph.ainvoke(graph_input, config={"configurable": {"thread_id": conversation.id}})
        # The tool returns a tuple of (message, MaxRecordingUniversalFilters)
        return result

    return callable


class FilterGenerationCorrectness(Scorer):
    """Score the correctness of generated filters."""

    def _name(self):
        return "filter_generation_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        try:
            actual_filters = output["generated_filter_options"]["data"]
            actual_filters = MaxRecordingUniversalFilters(**actual_filters)
        except Exception as e:
            logger.exception(f"Error parsing filters: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid filter structure"})

        score = 0.0
        total_checks = 0

        # Check date_from
        if expected.date_from:
            total_checks += 1
            if actual_filters.date_from == expected.date_from:
                score += 1.0

        # Check date_to
        if expected.date_to is not None:
            total_checks += 1
            if actual_filters.date_to == expected.date_to:
                score += 1.0

        # Check duration
        if expected.duration:
            total_checks += 1
            if actual_filters.duration == expected.duration:
                score += 1.0

        # Check filter_group structure
        if expected.filter_group:
            total_checks += 1
            if self._compare_filter_groups(actual_filters.filter_group, expected.filter_group):
                score += 1.0

        # Check filter_test_accounts
        if expected.filter_test_accounts is not None:
            total_checks += 1
            if actual_filters.filter_test_accounts == expected.filter_test_accounts:
                score += 1.0

        # Check order
        if expected.order:
            total_checks += 1
            if actual_filters.order == expected.order:
                score += 1.0

        final_score = score / total_checks if total_checks > 0 else 0.0
        return Score(
            name=self._name(), score=final_score, metadata={"total_checks": total_checks, "passed_checks": score}
        )

    def _run_eval_sync(self, output, expected=None, **kwargs):
        try:
            actual_filters = output["generated_filter_options"]["data"]
            actual_filters = MaxRecordingUniversalFilters(**actual_filters)
        except Exception as e:
            logger.exception(f"Error parsing filters: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid filter structure"})

        score = 0.0
        total_checks = 0

        # Check date_from
        if expected.date_from:
            total_checks += 1
            if actual_filters.date_from == expected.date_from:
                score += 1.0

        # Check date_to
        if expected.date_to is not None:
            total_checks += 1
            if actual_filters.date_to == expected.date_to:
                score += 1.0

        # Check duration
        if expected.duration:
            total_checks += 1
            if actual_filters.duration == expected.duration:
                score += 1.0

        # Check filter_group structure
        if expected.filter_group:
            total_checks += 1
            if self._compare_filter_groups(actual_filters.filter_group, expected.filter_group):
                score += 1.0

        # Check filter_test_accounts
        if expected.filter_test_accounts is not None:
            total_checks += 1
            if actual_filters.filter_test_accounts == expected.filter_test_accounts:
                score += 1.0

        # Check order
        if expected.order:
            total_checks += 1
            if actual_filters.order == expected.order:
                score += 1.0

        final_score = score / total_checks if total_checks > 0 else 0.0
        return Score(
            name=self._name(), score=final_score, metadata={"total_checks": total_checks, "passed_checks": score}
        )

    def _compare_filter_groups(self, actual, expected):
        """Compare filter group structures."""
        if actual.type != expected.type:
            return False

        if len(actual.values) != len(expected.values):
            return False

        # Simple comparison - in a real implementation you might want more sophisticated matching
        return True


@pytest.mark.django_db
async def eval_tool_search_session_recordings(call_search_session_recordings):
    await MaxEval(
        experiment_name="tool_search_session_recordings",
        task=call_search_session_recordings,
        scores=[FilterGenerationCorrectness()],
        data=[
            # Test basic filter generation for mobile devices
            EvalCase(
                input="Show me recordings from mobile devices",
                expected=MaxRecordingUniversalFilters(
                    **{
                        "date_from": "-7d",
                        "date_to": None,
                        "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gt"}],
                        "filter_group": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$device_type",
                                            "type": "event",
                                            "value": ["Mobile"],
                                            "operator": "exact",
                                        }
                                    ],
                                }
                            ],
                        },
                        "filter_test_accounts": True,
                        "order": "start_time",
                    }
                ),
            ),
            # Test date range filtering
            EvalCase(
                input="Show recordings from the last 24 hours",
                expected=MaxRecordingUniversalFilters(**{**current_filters, "date_from": "-1d"}),
            ),
            # Test location filtering
            EvalCase(
                input="Show recordings for users located in the US",
                expected=MaxRecordingUniversalFilters(
                    **{
                        **current_filters,
                        "filter_group": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$geoip_country_code",
                                            "type": "person",
                                            "value": ["US"],
                                            "operator": "exact",
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ),
            ),
            # Test browser-specific filtering
            EvalCase(
                input="Show recordings from Chrome users",
                expected=MaxRecordingUniversalFilters(
                    **{
                        **current_filters,
                        "filter_group": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {"key": "$browser", "type": "event", "value": ["Chrome"], "operator": "exact"}
                                    ],
                                }
                            ],
                        },
                    }
                ),
            ),
        ],
    )
