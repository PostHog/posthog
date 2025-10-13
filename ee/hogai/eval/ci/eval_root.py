import json

import pytest

from braintrust import EvalCase

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ToolRelevance


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.END,
                "search_documentation": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(messages: str | list[AssistantMessageUnion]) -> AssistantMessage:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages)] if isinstance(messages, str) else messages
        )
        raw_state = await graph.ainvoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
async def eval_root(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="root",
        task=call_root,
        scores=[ToolRelevance(semantic_similarity_args={"query_description"})],
        data=[
            EvalCase(
                input="Create an SQL insight to calculate active users recently",
                expected=AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            ),
            EvalCase(
                input="Write SQL to calculate active users recently",
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            ),
            # Should propagate the dates from the previous insight request
            EvalCase(
                input=[
                    HumanMessage(content="what is the trend of pageviews ytd 2025"),
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            AssistantToolCall(
                                id="call_vaTlpWMBgGyvYVIMfj1ecW8F",
                                name="create_and_query_insight",
                                args={
                                    "query_kind": "trends",
                                    "query_description": "Trend of pageviews year-to-date 2025",
                                },
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        tool_call_id="call_vaTlpWMBgGyvYVIMfj1ecW8F",
                        content=json.dumps(
                            {
                                "query_kind": "trends",
                                "query_description": "Here is the results table of the TrendsQuery I created to answer your latest question: ``` Date|$pageview 2025-01-01|6982 2025-02-01|9953 2025-03-01|7507 2025-04-01|795 2025-05-01|3 ``` The current date and time is 2025-05-01 09:07:56 UTC, which is 2025-05-01 09:07:56 in this project's timezone (UTC). It's expected that the data point for the current period can have a drop in value, as data collection is still ongoing for it. Do not point this out.",
                            }
                        ),
                    ),
                    AssistantMessage(
                        content="Here's the trend of pageviews for the year-to-date 2025: - January: 6,982 pageviews - February: 9,953 pageviews - March: 7,507 pageviews - April: 795 pageviews - May (so far): 3 pageviews Looks like February was a busy month! If you have any more questions or need further insights, just let me know!"
                    ),
                    HumanMessage(content="list the users"),
                ],
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "sql",
                        "query_description": "List all users who have completed a page view in year-to-date 2025.",
                    },
                ),
            ),
            # When the company name appears in the query results, it should NOT confuse the agent and it should still generate a new insight
            EvalCase(
                input=[
                    HumanMessage(content="List all user names who have completed a page view YTD"),
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            AssistantToolCall(
                                id="call_XdLOyLrHbjoBBACDCZd8WyNS",
                                name="create_and_query_insight",
                                args={
                                    "query_kind": "sql",
                                    "query_description": "List all user names who have completed a page view Year-To-Date (YTD).",
                                },
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        tool_call_id="call_XdLOyLrHbjoBBACDCZd8WyNS",
                        content=json.dumps(
                            {
                                "query_kind": "sql",
                                "query_description": 'You\'ll be given a JSON object with the results of a query.\n\nHere is the generated ClickHouse SQL query used to retrieve the results:\n\n```\nSELECT DISTINCT person.properties.name AS user_name\nFROM events\nWHERE event = \'$pageview\'\n  AND toYear(timestamp) = toYear(now())\n```\n\nYou\'ll be given a JSON object with the results of a query.\n\nHere is the results table of the HogQLQuery I created to answer your latest question:\n\n```\n[[null],["Mario Bridges"],["Alexander Dickson"],["YCombinator"],["Andrea Dickson"]]\n```\n\nThe current date and time is 2025-05-01 10:12:06 UTC, which is 2025-05-01 10:12:06 in this project\'s timezone (UTC).\nIt\'s expected that the data point for the current period can have a drop in value, as data collection is still ongoing for it. Do not point this out.',
                            }
                        ),
                    ),
                    AssistantMessage(
                        content="Here's the list of user names who have completed a page view Year-To-Date (YTD):\n\n- Mario Bridges\n- Alexander Dickson\n- YCombinator\n- Andrea Dickson\n\nThat's quite a crowd! If you need anything else, just let me know!"
                    ),
                    HumanMessage(content="give me a list of the companies only associated with the users"),
                ],
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "sql",
                        "query_description": "List all companies who have completed a page view Year-To-Date (YTD).",
                    },
                ),
            ),
            # Must reuse the previous data
            EvalCase(
                input=[
                    HumanMessage(content="List all user names who have completed a page view YTD"),
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            AssistantToolCall(
                                id="call_XdLOyLrHbjoBBACDCZd8WyNS",
                                name="create_and_query_insight",
                                args={
                                    "query_kind": "sql",
                                    "query_description": "List all user names who have completed a page view Year-To-Date (YTD).",
                                },
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        tool_call_id="call_XdLOyLrHbjoBBACDCZd8WyNS",
                        content=json.dumps(
                            {
                                "query_kind": "sql",
                                "query_description": 'You\'ll be given a JSON object with the results of a query.\n\nHere is the generated ClickHouse SQL query used to retrieve the results:\n\n```\nSELECT DISTINCT person.properties.name AS user_name\nFROM events\nWHERE event = \'$pageview\'\n  AND toYear(timestamp) = toYear(now())\n```\n\nYou\'ll be given a JSON object with the results of a query.\n\nHere is the results table of the HogQLQuery I created to answer your latest question:\n\n```\n[[null],["Mario Bridges"],["Alexander Dickson"],["YCombinator"],["Andrea Dickson"]]\n```\n\nThe current date and time is 2025-05-01 10:12:06 UTC, which is 2025-05-01 10:12:06 in this project\'s timezone (UTC).\nIt\'s expected that the data point for the current period can have a drop in value, as data collection is still ongoing for it. Do not point this out.',
                            }
                        ),
                    ),
                    AssistantMessage(
                        content="Here's the list of user names who have completed a page view Year-To-Date (YTD):\n\n- Mario Bridges\n- Alexander Dickson\n- YCombinator\n- Andrea Dickson\n\nThat's quite a crowd! If you need anything else, just let me know!"
                    ),
                    HumanMessage(content="List all user names who have completed a page view YTD"),
                ],
                expected=None,
            ),
            # Documentation search when the user asks about SDK integration or instrumentation
            EvalCase(
                input="import posthog from 'posthog-js' posthog.captureException(error) in my react app i manually capture exceptions but i don't see them on the dashboard",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_oejkj9HpAcIVAqTjxaXaofyA",
                ),
            ),
            # Basic PostHog product questions
            EvalCase(
                input="How do I set up event tracking in PostHog?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_1",
                ),
            ),
            EvalCase(
                input="What is a cohort in PostHog and how do I create one?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_2",
                ),
            ),
            EvalCase(
                input="How does PostHog's session recording work?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_3",
                ),
            ),
            EvalCase(
                input="Can you explain PostHog's feature flags functionality?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_4",
                ),
            ),
            # SDK and integration questions
            EvalCase(
                input="How do I install the PostHog SDK for Python?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_5",
                ),
            ),
            EvalCase(
                input="posthog js sdk not working in my next.js app",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_6",
                ),
            ),
            EvalCase(
                input="How to track custom events with posthog react library",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_7",
                ),
            ),
            EvalCase(
                input="posthog.capture() vs posthog.track() whats the difference",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_8",
                ),
            ),
            # Feature-specific questions
            EvalCase(
                input="How do I create a funnel analysis in PostHog?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_9",
                ),
            ),
            EvalCase(
                input="What's the difference between trends and insights in PostHog?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_10",
                ),
            ),
            EvalCase(
                input="How do I set up A/B testing with PostHog feature flags?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_11",
                ),
            ),
            EvalCase(
                input="posthog dashboard widgets how to customize them",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_12",
                ),
            ),
            # Terse/messy user input
            EvalCase(
                input="ph not tracking events???",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_13",
                ),
            ),
            EvalCase(
                input="help feature flag setup",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_14",
                ),
            ),
            EvalCase(
                input="posthog broken",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_15",
                ),
            ),
            EvalCase(
                input="sdk integration issues react native",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_16",
                ),
            ),
            EvalCase(
                input="cant see recordings",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_17",
                ),
            ),
            # Troubleshooting and debugging
            EvalCase(
                input="My PostHog events aren't showing up in the dashboard, what could be wrong?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_18",
                ),
            ),
            EvalCase(
                input="Session recordings are blank, how do I fix this?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_19",
                ),
            ),
            EvalCase(
                input="PostHog feature flags not working in production environment",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_20",
                ),
            ),
            EvalCase(
                input="Why are my PostHog cohorts not updating automatically?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_21",
                ),
            ),
            # Configuration and setup questions
            EvalCase(
                input="How do I configure PostHog for GDPR compliance?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_22",
                ),
            ),
            EvalCase(
                input="What are the different PostHog deployment options?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_23",
                ),
            ),
            EvalCase(
                input="posthog self hosted vs cloud which one should i choose",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_24",
                ),
            ),
            # API and integration questions
            EvalCase(
                input="How do I use PostHog's REST API to query events?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_25",
                ),
            ),
            EvalCase(
                input="PostHog webhook integration with Slack how to set up",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_26",
                ),
            ),
            EvalCase(
                input="can posthog integrate with segment?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_27",
                ),
            ),
            # Performance and limits
            EvalCase(
                input="What are PostHog's rate limits for event ingestion?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_28",
                ),
            ),
            EvalCase(
                input="my posthog is slow how to optimize performance",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_29",
                ),
            ),
            # Mobile and platform-specific
            EvalCase(
                input="PostHog iOS SDK setup guide",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_30",
                ),
            ),
            EvalCase(
                input="android posthog tracking not working",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_31",
                ),
            ),
            EvalCase(
                input="flutter posthog plugin how to use",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_32",
                ),
            ),
            # Ensure calls docs, not insights
            EvalCase(
                input="Is there a field on a person I can use to show the last time they interacted with the platform?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_33",
                ),
            ),
            EvalCase(
                input="Can I see which browser or device type a user is using from the default event properties?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_34",
                ),
            ),
            EvalCase(
                input="What geographic information does PostHog automatically capture about my users?",
                expected=AssistantToolCall(
                    name="search_documentation",
                    args={},
                    id="call_doc_search_35",
                ),
            ),
            # Ensure calls insights, not documentation
            EvalCase(
                input="Show me all events where the default $browser property equals Chrome",
                expected=AssistantToolCall(
                    name="create_and_query_insight",
                    args={
                        "query_kind": "sql",
                        "query_description": "Show all events where the $browser property equals Chrome",
                    },
                    id="call_insight_default_props_1",
                ),
            ),
            EvalCase(
                input="How many unique users have the default $device_type property as mobile?",
                expected=AssistantToolCall(
                    name="create_and_query_insight",
                    args={
                        "query_kind": "sql",
                        "query_description": "Count unique users who have the $device_type property set to mobile",
                    },
                    id="call_insight_default_props_2",
                ),
            ),
            # Ensure we try and navigate to the relevant page when asked about specific topics
            EvalCase(
                input="What's my MRR?",
                expected=AssistantToolCall(
                    name="navigate",
                    args={"page_key": "revenueAnalytics"},
                    id="call_navigate_1",
                ),
            ),
            EvalCase(
                input="Can you help me create a survey to collect NPS ratings?",
                expected=AssistantToolCall(
                    name="navigate",
                    args={"page_key": "surveys"},
                    id="call_navigate_1",
                ),
            ),
            EvalCase(
                input="Give me the signup to purchase conversion rate for the dates between 8 Jul and 9 Sep",
                expected=AssistantToolCall(
                    name="create_and_query_insight",
                    args={
                        "query_description": "Calculate the signup to purchase conversion rate for dates between July 8 and September 9",
                    },
                    id="call_specific_conversion_rate",
                ),
            ),
            EvalCase(
                input="Show me daily active users for the past month",
                expected=AssistantToolCall(
                    name="create_and_query_insight",
                    args={
                        "query_description": "Daily active users for the past month",
                    },
                    id="call_dau_past_month",
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
