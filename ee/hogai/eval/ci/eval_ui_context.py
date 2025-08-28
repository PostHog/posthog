import pytest

from braintrust import EvalCase

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    HumanMessage,
    MaxActionContext,
    MaxEventContext,
    MaxUIContext,
)

from posthog.models.action.action import Action
from posthog.models.team.team import Team

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ToolRelevance


@pytest.fixture
def call_root_with_ui_context(demo_org_team_user):
    """Fixture to test root node with UI context containing actions and events"""
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.END,
                "docs": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(input_dict: dict) -> AssistantMessage:
        messages = input_dict["messages"]
        ui_context = input_dict.get("ui_context")
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages, ui_context=ui_context)] if isinstance(messages, str) else messages
        )
        raw_state = await graph.ainvoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.fixture
def sample_action(demo_org_team_user):
    """Create a sample action for testing"""
    team: Team = demo_org_team_user[1]
    action = Action.objects.create(
        team=team,
        name="Purchase Completed",
        description="User completed a purchase transaction",
    )
    return action


@pytest.mark.django_db
async def eval_ui_context_actions(call_root_with_ui_context, sample_action, pytestconfig):
    """Test that actions in UI context are properly used in RAG context retrieval"""
    await MaxPublicEval(
        experiment_name="ui_context_actions",
        task=call_root_with_ui_context,
        scores=[
            ToolRelevance(semantic_similarity_args={"query_description"}),
        ],
        data=[
            EvalCase(
                input={
                    "messages": "Show me trends for this action",
                    "ui_context": MaxUIContext(
                        actions=[
                            MaxActionContext(
                                id=sample_action.id,
                                name=sample_action.name,
                                description=sample_action.description,
                            )
                        ]
                    ),
                },
                expected=AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "trends",
                        "query_description": "Show trends for purchase completions using the Purchase Completed action",
                    },
                ),
            ),
            # Test with multiple actions
            EvalCase(
                input={
                    "messages": "Create a funnel using these actions",
                    "ui_context": MaxUIContext(
                        actions=[
                            MaxActionContext(
                                id=sample_action.id,
                                name="Purchase Completed",
                                description="User completed a purchase transaction",
                            ),
                            MaxActionContext(
                                id=sample_action.id + 1,
                                name="User Signup",
                                description="User created a new account",
                            ),
                        ]
                    ),
                },
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "funnel",
                        "query_description": "Create a funnel from User Signup action to Purchase Completed action",
                    },
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_ui_context_events(call_root_with_ui_context, pytestconfig):
    """Test that events in UI context are properly used in taxonomy agent"""
    await MaxPublicEval(
        experiment_name="ui_context_events",
        task=call_root_with_ui_context,
        scores=[
            ToolRelevance(semantic_similarity_args={"query_description"}),
        ],
        data=[
            EvalCase(
                input={
                    "messages": "Show me trends for this event",
                    "ui_context": MaxUIContext(
                        events=[
                            MaxEventContext(
                                id="1",
                                name="checkout_started",
                                description="User initiated the checkout process",
                            )
                        ]
                    ),
                },
                expected=AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "trends",
                        "query_description": "Show trends for checkout_started events",
                    },
                ),
            ),
            EvalCase(
                input={
                    "messages": "How many users have triggered these events",
                    "ui_context": MaxUIContext(
                        events=[
                            MaxEventContext(
                                id="1",
                                name="feature_used",
                                description="User interacted with a premium feature",
                            ),
                            MaxEventContext(
                                id="2",
                                name="content_shared",
                                description="User shared content on social media",
                            ),
                        ]
                    ),
                },
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "trends",
                        "query_description": "Show trends for feature_used and content_shared events",
                    },
                ),
            ),
            # Test mixed context with both events and actions
            EvalCase(
                input={
                    "messages": "Create a funnel using these event and action",
                    "ui_context": MaxUIContext(
                        events=[
                            MaxEventContext(
                                id="1",
                                name="button_clicked",
                                description="User clicked a CTA button",
                            )
                        ],
                        actions=[
                            MaxActionContext(
                                id=1,
                                name="Conversion Goal",
                                description="User reached conversion milestone",
                            )
                        ],
                    ),
                },
                expected=AssistantToolCall(
                    id="3",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "funnel",
                        "query_description": "Create a funnel from button_clicked event to Conversion Goal action",
                    },
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
