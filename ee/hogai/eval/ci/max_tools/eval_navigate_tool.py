import pytest

from braintrust import EvalCase
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantNavigateUrl, AssistantToolCall, FailureMessage, HumanMessage

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ...base import MaxPublicEval
from ...scorers import ToolRelevance

TOOLS_PROMPT = """
- **actions**: Combine several related events into one, which you can then analyze in insights and dashboards as if it were a single event.
- **cohorts**: A catalog of identified persons and your created cohorts.
- **dashboards**: Create and manage your dashboards
- **earlyAccessFeatures**: Allow your users to individually enable or disable features that are in public beta.
- **errorTracking**: Track and analyze your error tracking data to understand and fix issues. [tools: Filter issues, Find impactful issues]
- **experiments**: Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or if they are likely just a chance occurrence.
- **featureFlags**: Use feature flags to safely deploy and roll back new features in an easy-to-manage way. Roll variants out to certain groups, a percentage of users, or everyone all at once.
- **notebooks**: Notebooks are a way to organize your work and share it with others.
- **persons**: A catalog of all the people behind your events
- **insights**: Track, analyze, and experiment with user behavior.
- **insightNew** [tools: Edit the insight]
- **savedInsights**: Track, analyze, and experiment with user behavior.
- **alerts**: Track, analyze, and experiment with user behavior.
- **replay**: Replay recordings of user sessions to understand how users interact with your product or website. [tools: Search recordings]
- **revenueAnalytics**: Track and analyze your revenue metrics to understand your business performance and growth. [tools: Filter revenue analytics]
- **surveys**: Create surveys to collect feedback from your users [tools: Create surveys, Analyze survey responses]
- **webAnalytics**: Analyze your web analytics data to understand website performance and user behavior.
- **webAnalyticsWebVitals**: Analyze your web analytics data to understand website performance and user behavior.
- **activity**: A catalog of all user interactions with your app or website.
- **sqlEditor**: Write and execute SQL queries against your data warehouse [tools: Write and tweak SQL]
- **heatmaps**: Heatmaps are a way to visualize user behavior on your website.
""".strip()


class EvalInput(BaseModel):
    messages: str | list[AssistantMessageUnion]
    current_page: str = Field(default="")


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(lambda state: AssistantNodeName.END)
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(input: EvalInput) -> AssistantMessage:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=input.messages)] if isinstance(input.messages, str) else input.messages
        )
        raw_state = await graph.ainvoke(
            initial_state,
            {
                "configurable": {
                    "thread_id": conversation.id,
                    "contextual_tools": {
                        "navigate": {"scene_descriptions": TOOLS_PROMPT, "current_page": input.current_page}
                    },
                }
            },
        )
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
async def eval_root_navigate_tool(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="root_navigate_tool",
        task=call_root,
        scores=[ToolRelevance(semantic_similarity_args={"query_description"})],
        data=[
            # Shouldn't navigate to the insights page
            EvalCase(
                input=EvalInput(messages="build pageview insight"),
                expected=AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={
                        "query_description": "Create a trends insight showing pageview events over time. Track the $pageview event to visualize how many pageviews are happening."
                    },
                ),
            ),
            # Should navigate to the persons page
            EvalCase(
                input=EvalInput(
                    messages="I added tracking of persons, but I can't find where the persons are in the app"
                ),
                expected=AssistantToolCall(
                    id="1",
                    name="navigate",
                    args={"page_key": AssistantNavigateUrl.PERSONS.value},
                ),
            ),
            # Should navigate to the surveys page
            EvalCase(
                input=EvalInput(
                    messages="were is my survey. I jsut created a survey and  save it as draft, I cannot find it now",
                    current_page="/project/1/surveys/new",
                ),
                expected=AssistantToolCall(
                    id="1",
                    name="navigate",
                    args={"page_key": AssistantNavigateUrl.SURVEYS.value},
                ),
            ),
            # Should not navigate to the SQL editor
            EvalCase(
                input=EvalInput(
                    messages="I need a query written in SQL to tell me what all of my identified events are for any given day."
                ),
                expected=AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={"query_description": "All identified events for any given day"},
                ),
            ),
            # Should just say that the query failed
            EvalCase(
                input=EvalInput(
                    messages=[
                        HumanMessage(
                            content="I need a query written in SQL to tell me what all of my identified events are for any given day."
                        ),
                        FailureMessage(
                            content="An unknown failure occurred while accessing the `events` table",
                        ),
                    ]
                ),
                expected=None,
            ),
        ],
        pytestconfig=pytestconfig,
    )
