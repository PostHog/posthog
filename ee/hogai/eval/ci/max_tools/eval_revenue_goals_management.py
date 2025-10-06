import logging
from typing import Any

import pytest

from braintrust import EvalCase, Score
from braintrust_core.score import Scorer
from deepdiff import DeepDiff

from posthog.schema import MrrOrGross, RevenueAnalyticsAssistantGoalsOutput, RevenueAnalyticsGoal

from posthog.models.team.team_revenue_analytics_config import TeamRevenueAnalyticsConfig

from products.revenue_analytics.backend.ai.tools.revenue_goals.prompts import USER_GOALS_PROMPT
from products.revenue_analytics.backend.max_tools import RevenueGoalsGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.models.assistant import Conversation

from ...base import MaxPublicEval

logger = logging.getLogger(__name__)


DUMMY_CURRENT_GOALS = RevenueAnalyticsAssistantGoalsOutput(
    goals=[
        RevenueAnalyticsGoal(
            name="Q2 MRR Target",
            goal=50000.0,
            due_date="2024-06-30",
            mrr_or_gross=MrrOrGross.MRR,
        ),
        RevenueAnalyticsGoal(
            name="Annual Revenue Goal",
            goal=1000000.0,
            due_date="2024-12-31",
            mrr_or_gross=MrrOrGross.GROSS,
        ),
    ]
)


@pytest.fixture
def call_manage_revenue_goals(demo_org_team_user):
    graph = RevenueGoalsGraph(demo_org_team_user[1], demo_org_team_user[2]).compile_full_graph(
        checkpointer=DjangoCheckpointer()
    )

    # Return a builder to let us mock the DB state with different initial goals
    def callable_builder(initial_goals=DUMMY_CURRENT_GOALS.goals):
        async def callable(change: str) -> dict:
            conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

            # Set up initial goals in the database for testing
            config, _ = await TeamRevenueAnalyticsConfig.objects.aget_or_create(team=demo_org_team_user[1])
            config.goals = [goal.model_dump() for goal in initial_goals]
            await config.asave()

            graph_input: dict[str, Any] = {
                "change": USER_GOALS_PROMPT.format(change=change),
                "output": None,
                "tool_progress_messages": [],
            }

            result = await graph.ainvoke(graph_input, config={"configurable": {"thread_id": conversation.id}})
            return result

        return callable

    return callable_builder


class GoalsManagementCorrectness(Scorer):
    """Score the correctness of generated goals management actions."""

    def _name(self):
        return "goals_management_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        try:
            actual_goals = RevenueAnalyticsAssistantGoalsOutput.model_validate(output["output"])
        except Exception as e:
            logger.exception(f"Error parsing goals: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid goals structure"})

        # Convert both objects to dict for deepdiff comparison
        actual_dict = actual_goals.model_dump()
        expected_dict = expected.model_dump()

        # Use deepdiff to find differences, but ignore name fields in goals
        diff = DeepDiff(
            expected_dict,
            actual_dict,
            ignore_order=True,
            report_repetition=True,
            exclude_regex_paths=r"root\['goals'\]\[\d+\]\['name'\]",  # Ignore goal names
        )

        if not diff:
            return Score(name=self._name(), score=1.0, metadata={"reason": "Perfect match (ignoring goal names)"})

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
        if (
            "intermediate_steps" in output
            and len(output["intermediate_steps"]) > 0
            and output["intermediate_steps"][-1][0].tool == "ask_user_for_help"
        ):
            return Score(
                name=self._name(), score=1, metadata={"reason": "LLM returned valid ask_user_for_help response"}
            )

        if "output" in output and output["output"] is not None:
            return Score(name=self._name(), score=0, metadata={"reason": "LLM returned goals output"})

        return Score(
            name=self._name(),
            score=0,
            metadata={"reason": "LLM did not return valid ask_user_for_help response"},
        )


class GoalsActionCorrectness(Scorer):
    """Score the correctness of specific goal actions (add, update, remove, list)."""

    def _name(self):
        return "goals_action_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        try:
            actual_goals = RevenueAnalyticsAssistantGoalsOutput.model_validate(output["output"])
        except Exception as e:
            logger.exception(f"Error parsing goals: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid goals structure"})

        # Check if the action was performed correctly by comparing goal counts and specific goals
        expected_goals = expected.goals
        actual_goals_list = actual_goals.goals

        # For add operations, we expect one more goal
        # For remove operations, we expect one fewer goal
        # For update operations, we expect the same number but different content
        # For list operations, we expect the same goals

        if len(actual_goals_list) == len(expected_goals):
            # Check if goals match (for updates or lists) - ignore name differences
            goals_match = all(
                any(
                    actual.goal == expected.goal
                    and actual.due_date == expected.due_date
                    and actual.mrr_or_gross == expected.mrr_or_gross
                    for actual in actual_goals_list
                )
                for expected in expected_goals
            )
            if goals_match:
                return Score(
                    name=self._name(), score=1.0, metadata={"reason": "Goals match perfectly (ignoring names)"}
                )
            else:
                return Score(
                    name=self._name(), score=0.5, metadata={"reason": "Goal count matches but content differs"}
                )
        else:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"Expected {len(expected_goals)} goals, got {len(actual_goals_list)}"},
            )


@pytest.mark.django_db
async def eval_tool_manage_revenue_goals(call_manage_revenue_goals, pytestconfig):
    await MaxPublicEval(
        experiment_name="tool_manage_revenue_goals",
        task=call_manage_revenue_goals(),
        scores=[GoalsManagementCorrectness(), GoalsActionCorrectness()],
        data=[
            # Test adding a new goal (should add to existing goals)
            EvalCase(
                input="Add a goal to reach $75,000 MRR by March 31st, 2025",
                expected=RevenueAnalyticsAssistantGoalsOutput(
                    goals=[
                        RevenueAnalyticsGoal(
                            name="Q2 MRR Target",  # Existing goal
                            goal=50000.0,
                            due_date="2024-06-30",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                        RevenueAnalyticsGoal(
                            name="Annual Revenue Goal",  # Existing goal
                            goal=1000000.0,
                            due_date="2024-12-31",
                            mrr_or_gross=MrrOrGross.GROSS,
                        ),
                        RevenueAnalyticsGoal(
                            name="Q1 2025 MRR Target",  # New goal (name may vary)
                            goal=75000.0,
                            due_date="2025-03-31",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                    ]
                ),
            ),
            # Test updating an existing goal
            EvalCase(
                input="Update the Q2 MRR Target to 60k",
                expected=RevenueAnalyticsAssistantGoalsOutput(
                    goals=[
                        RevenueAnalyticsGoal(
                            name="Q2 MRR Target",
                            goal=60000.0,
                            due_date="2024-06-30",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                        RevenueAnalyticsGoal(
                            name="Annual Revenue Goal",
                            goal=1000000.0,
                            due_date="2024-12-31",
                            mrr_or_gross=MrrOrGross.GROSS,
                        ),
                    ]
                ),
            ),
            # Test removing a goal
            EvalCase(
                input="Remove the Annual Revenue Goal",
                expected=RevenueAnalyticsAssistantGoalsOutput(
                    goals=[
                        RevenueAnalyticsGoal(
                            name="Q2 MRR Target",
                            goal=50000.0,
                            due_date="2024-06-30",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                    ]
                ),
            ),
            # Test listing goals (should return current goals)
            EvalCase(
                input="Show me my current revenue goals",
                expected=DUMMY_CURRENT_GOALS,
            ),
            # Test adding a gross revenue goal
            EvalCase(
                input="Add a goal to reach $2M in gross revenue by the end of 2025",
                expected=RevenueAnalyticsAssistantGoalsOutput(
                    goals=[
                        RevenueAnalyticsGoal(
                            name="Q2 MRR Target",
                            goal=50000.0,
                            due_date="2024-06-30",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                        RevenueAnalyticsGoal(
                            name="Annual Revenue Goal",
                            goal=1000000.0,
                            due_date="2024-12-31",
                            mrr_or_gross=MrrOrGross.GROSS,
                        ),
                        RevenueAnalyticsGoal(
                            name="2025 Gross Revenue Target",
                            goal=2000000.0,
                            due_date="2025-12-31",
                            mrr_or_gross=MrrOrGross.GROSS,
                        ),
                    ]
                ),
            ),
            # More complex test with multiple changes
            EvalCase(
                input="Remove the annual revenue goal, and add a new MRR one, 75k, to the end of Q3 2024",
                expected=RevenueAnalyticsAssistantGoalsOutput(
                    goals=[
                        RevenueAnalyticsGoal(
                            name="Q2 MRR Target",
                            goal=50000.0,
                            due_date="2024-06-30",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                        RevenueAnalyticsGoal(
                            name="Q3 MRR Target",
                            goal=75000.0,
                            due_date="2024-09-30",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                    ]
                ),
            ),
        ],
        pytestconfig=pytestconfig,
        max_concurrency=1,  # Tests depend on DB state, let's run this one after the other
    )


@pytest.mark.django_db
async def eval_tool_manage_revenue_goals_from_empty(call_manage_revenue_goals, pytestconfig):
    """Test revenue goals management starting with no existing goals."""
    await MaxPublicEval(
        experiment_name="tool_manage_revenue_goals_from_empty",
        task=call_manage_revenue_goals(initial_goals=[]),
        scores=[GoalsManagementCorrectness(), GoalsActionCorrectness()],
        data=[
            # Test adding the first goal
            EvalCase(
                input="Add a goal to reach $50,000 MRR by December 31st, 2024",
                expected=RevenueAnalyticsAssistantGoalsOutput(
                    goals=[
                        RevenueAnalyticsGoal(
                            name="Q4 MRR Target",  # Name may vary
                            goal=50000.0,
                            due_date="2024-12-31",
                            mrr_or_gross=MrrOrGross.MRR,
                        ),
                    ]
                ),
            ),
        ],
        pytestconfig=pytestconfig,
        max_concurrency=1,
    )


@pytest.mark.django_db
async def eval_tool_manage_revenue_goals_ask_user_for_help(call_manage_revenue_goals, pytestconfig):
    await MaxPublicEval(
        experiment_name="tool_manage_revenue_goals_ask_user_for_help",
        task=call_manage_revenue_goals(),
        scores=[AskUserForHelp()],
        data=[
            EvalCase(input="Add a revenue goal", expected="clarify what the revenue goal should look like"),
            EvalCase(
                input="Add a revenue goal to the end of the year", expected="clarify what the last day of the year is"
            ),
            EvalCase(
                input="Add a revenue goal to the end of the quarter",
                expected="clarify what the last day of the quarter is",
            ),
        ],
        pytestconfig=pytestconfig,
        max_concurrency=1,
    )
