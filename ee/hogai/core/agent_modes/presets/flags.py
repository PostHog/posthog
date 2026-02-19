from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from products.experiments.backend.max_tools import CreateExperimentTool, ExperimentSummaryTool, SessionReplaySummaryTool
from products.feature_flags.backend.max_tools import CreateFeatureFlagTool

from ee.hogai.chat_agent.executables import ChatAgentPlanExecutable, ChatAgentPlanToolsExecutable
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tools.todo_write import TodoWriteExample
from ee.hogai.utils.feature_flags import has_experiment_summary_tool_feature_flag

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


POSITIVE_EXAMPLE_CREATE_FLAG = """
User: Create a feature flag to roll out our new checkout flow to 25% of users
Assistant: I'll create a feature flag for the new checkout flow with a 25% rollout.
*Uses create_feature_flag with key: "new-checkout-flow", rollout_percentage: 25*
""".strip()

POSITIVE_EXAMPLE_CREATE_FLAG_REASONING = """
The assistant used create_feature_flag because:
1. The user wants to create a simple rollout flag
2. The request specifies a percentage (25%) which maps to rollout_percentage
3. No A/B testing variants are needed, just a gradual rollout
""".strip()

POSITIVE_EXAMPLE_CREATE_EXPERIMENT = """
User: I want to run an A/B test on our pricing page
Assistant: I'll help you set up an A/B test for the pricing page. This requires creating a multivariate feature flag first, then linking it to an experiment.
*Creates todo list with the following items:*
1. Create multivariate feature flag with control and test variants
2. Create experiment linked to the feature flag
*Uses create_feature_flag with key: "pricing-page-experiment", variants: [control, test]*
After creating the flag, the assistant uses create_experiment to link it.
""".strip()

POSITIVE_EXAMPLE_CREATE_EXPERIMENT_REASONING = """
The assistant used the todo list because:
1. Creating an experiment requires two steps: first create a multivariate flag, then create the experiment
2. The create_experiment tool requires an existing feature flag with variants
3. Breaking this into steps ensures the flag is created before the experiment
""".strip()

POSITIVE_EXAMPLE_ANALYZE_EXPERIMENT = """
User: How is our pricing experiment performing?
Assistant: I'll analyze the results of your pricing experiment.
*Uses experiment_results_summary to analyze the experiment*
""".strip()

POSITIVE_EXAMPLE_ANALYZE_EXPERIMENT_REASONING = """
The assistant used experiment_results_summary because:
1. The user wants to understand experiment performance
2. This tool provides statistical analysis and recommendations
3. It handles both Bayesian and Frequentist analysis automatically
""".strip()


class FlagsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_CREATE_FLAG,
            reasoning=POSITIVE_EXAMPLE_CREATE_FLAG_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_CREATE_EXPERIMENT,
            reasoning=POSITIVE_EXAMPLE_CREATE_EXPERIMENT_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_ANALYZE_EXPERIMENT,
            reasoning=POSITIVE_EXAMPLE_ANALYZE_EXPERIMENT_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = [CreateFeatureFlagTool, CreateExperimentTool, SessionReplaySummaryTool]
        if has_experiment_summary_tool_feature_flag(self._team, self._user):
            tools.append(ExperimentSummaryTool)
        return tools


MODE_DESCRIPTION = "Specialized mode for creating and managing feature flags and experiments. This mode allows you to create feature flags with property-based targeting and rollout percentages, set up A/B test experiments with multivariate flags, and analyze experiment results with statistical summaries."

flags_agent = AgentModeDefinition(
    mode=AgentMode.FLAGS,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=FlagsAgentToolkit,
)

chat_agent_plan_flags_agent = AgentModeDefinition(
    mode=AgentMode.FLAGS,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=FlagsAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
