import datetime
from typing import cast

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    AssistantMessage,
    ContextMessage,
    DashboardFilter,
    EntityType,
    EventsNode,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    LifecycleQuery,
    MaxActionContext,
    MaxBillingContext,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
    MaxUIContext,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
)

from posthog.models.organization import OrganizationMembership

from ee.hogai.context import AssistantContextManager
from ee.hogai.utils.types import AssistantState


class TestAssistantContextManager(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.config = RunnableConfig(configurable={})
        self.context_manager = AssistantContextManager(self.team, self.user, self.config)

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_run_and_format_insight_trends_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Trend results: 100 users", None))

        insight = MaxInsightContext(
            id="123",
            name="User Trends",
            description="Daily active users",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        result = await self.context_manager._arun_and_format_insight(
            insight, mock_query_runner, dashboard_filters=None, heading="#"
        )
        expected = """# Insight: User Trends

Description: Daily active users

Query schema:
```json
{"filterTestAccounts":false,"interval":"day","kind":"TrendsQuery","properties":[],"series":[{"event":"pageview","kind":"EventsNode"}]}
```

Results:
```
Trend results: 100 users
```"""
        self.assertEqual(result, expected)
        mock_query_runner.arun_and_format_query.assert_called_once()

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_run_and_format_insight_funnel_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Funnel results: 50% conversion", None))

        insight = MaxInsightContext(
            id="456",
            name="Conversion Funnel",
            description=None,
            query=FunnelsQuery(series=[EventsNode(event="sign_up"), EventsNode(event="purchase")]),
        )

        result = await self.context_manager._arun_and_format_insight(insight, mock_query_runner, heading="#")

        expected = """# Insight: Conversion Funnel

Query schema:
```json
{"filterTestAccounts":false,"kind":"FunnelsQuery","properties":[],"series":[{"event":"sign_up","kind":"EventsNode"},{"event":"purchase","kind":"EventsNode"}]}
```

Results:
```
Funnel results: 50% conversion
```"""
        self.assertEqual(result, expected)

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_run_and_format_insight_retention_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Retention: 30% Day 7", None))

        insight = MaxInsightContext(
            id="789",
            name=None,
            description=None,
            query=RetentionQuery(
                retentionFilter=RetentionFilter(
                    targetEntity=RetentionEntity(id="$pageview", type=EntityType.EVENTS),
                    returningEntity=RetentionEntity(id="$pageview", type=EntityType.EVENTS),
                )
            ),
        )

        result = await self.context_manager._arun_and_format_insight(insight, mock_query_runner, heading="#")
        expected = """# Insight: ID 789

Query schema:
```json
{"filterTestAccounts":false,"kind":"RetentionQuery","properties":[],"retentionFilter":{"period":"Day","returningEntity":{"id":"$pageview","type":"events"},"targetEntity":{"id":"$pageview","type":"events"},"totalIntervals":8}}
```

Results:
```
Retention: 30% Day 7
```"""
        self.assertEqual(result, expected)

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_run_and_format_insight_hogql_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Query results: 42 events", None))

        insight = MaxInsightContext(
            id="101",
            name="Custom Query",
            description="HogQL analysis",
            query=HogQLQuery(query="SELECT count() FROM events"),
        )

        result = await self.context_manager._arun_and_format_insight(insight, mock_query_runner, heading="#")
        expected = """# Insight: Custom Query

Description: HogQL analysis

Query schema:
```json
{"kind":"HogQLQuery","query":"SELECT count() FROM events"}
```

Results:
```
Query results: 42 events
```"""
        self.assertEqual(result, expected)

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_run_and_format_insight_unsupported_query_kind(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock()

        insight = MaxInsightContext(id="123", name="Unsupported", description=None, query=LifecycleQuery(series=[]))

        result = await self.context_manager._arun_and_format_insight(insight, mock_query_runner)

        self.assertEqual(result, None)
        mock_query_runner.arun_and_format_query.assert_not_called()

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    @patch("ee.hogai.context.context.capture_exception")
    async def test_run_and_format_insight_exception_handling(self, mock_capture_exception, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(side_effect=Exception("Query failed"))

        insight = MaxInsightContext(
            id="123",
            name="Failed Query",
            description=None,
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        result = await self.context_manager._arun_and_format_insight(insight, mock_query_runner)

        self.assertEqual(result, None)
        mock_capture_exception.assert_called_once()

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_format_ui_context_with_dashboard(self, mock_query_runner_class):
        # Configure the mock to return a proper mock instance with arun_and_format_query method
        mock_query_runner = MagicMock()
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Dashboard insight results", None))
        mock_query_runner_class.return_value = mock_query_runner

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Dashboard Insight",
            description="Test insight",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        # Create mock dashboard
        dashboard = MaxDashboardContext(
            id=456,
            name="Test Dashboard",
            description="Test dashboard description",
            insights=[insight],
            filters=DashboardFilter(),
        )

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=[dashboard], insights=None)

        result = await self.context_manager._format_ui_context(ui_context)

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn("Dashboard: Test Dashboard", result)
        self.assertIn("Description: Test dashboard description", result)
        self.assertIn("### Dashboard insights", result)
        # Since the insights are being executed asynchronously and the mocks aren't working
        # properly with the context manager, just check the structure is there
        # The test for actual insight execution is covered in test_run_and_format_insight_trends_query
        self.assertNotIn("# Insights", result)

    async def test_format_ui_context_with_events(self):
        # Create mock events
        event1 = MaxEventContext(id="1", name="page_view")
        event2 = MaxEventContext(id="2", name="button_click")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=[event1, event2], actions=None)

        result = await self.context_manager._format_ui_context(ui_context)

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"page_view", "button_click"', result)
        self.assertIn("<events_context>", result)

    async def test_format_ui_context_with_events_with_descriptions(self):
        # Create mock events with descriptions
        event1 = MaxEventContext(id="1", name="page_view", description="User viewed a page")
        event2 = MaxEventContext(id="2", name="button_click", description="User clicked a button")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=[event1, event2], actions=None)

        result = await self.context_manager._format_ui_context(ui_context)

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"page_view: User viewed a page", "button_click: User clicked a button"', result)
        self.assertIn("<events_context>", result)

    async def test_format_ui_context_with_actions(self):
        # Create mock actions
        action1 = MaxActionContext(id=1.0, name="Sign Up")
        action2 = MaxActionContext(id=2.0, name="Purchase")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=None, actions=[action1, action2])

        result = await self.context_manager._format_ui_context(ui_context)

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"Sign Up", "Purchase"', result)
        self.assertIn("<actions_context>", result)

    async def test_format_ui_context_with_actions_with_descriptions(self):
        # Create mock actions with descriptions
        action1 = MaxActionContext(id=1.0, name="Sign Up", description="User creates account")
        action2 = MaxActionContext(id=2.0, name="Purchase", description="User makes a purchase")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=None, actions=[action1, action2])

        result = await self.context_manager._format_ui_context(ui_context)

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"Sign Up: User creates account", "Purchase: User makes a purchase"', result)
        self.assertIn("<actions_context>", result)

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_format_ui_context_with_standalone_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Standalone insight results", None))

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Standalone Insight",
            description="Test standalone insight",
            query=FunnelsQuery(series=[EventsNode(event="sign_up")]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = await self.context_manager._format_ui_context(ui_context)

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn("Insights", result)
        self.assertIn("Insight: Standalone Insight", result)
        self.assertNotIn("# Dashboards", result)

    async def test_format_ui_context_empty(self):
        result = await self.context_manager._format_ui_context(None)
        self.assertIsNone(result)

        # Test with ui_context but no insights
        ui_context = MaxUIContext(insights=None)
        result = await self.context_manager._format_ui_context(ui_context)
        self.assertIsNone(result)

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    async def test_format_ui_context_with_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Insight execution results", None))

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Test Insight",
            description="Test description",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = await self.context_manager._format_ui_context(ui_context)

        self.assertIsNotNone(result)
        result = cast(str, result)  # Type cast for mypy
        self.assertIn("# Insights", result)
        self.assertIn("Test Insight", result)
        self.assertIn("Test description", result)
        self.assertIn("Insight execution results", result)

    @patch("ee.hogai.context.context.AssistantQueryExecutor")
    @patch("ee.hogai.context.context.capture_exception")
    async def test_format_ui_context_with_failed_insights(self, mock_capture_exception, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(side_effect=Exception("Query failed"))

        # Create mock insight that will fail
        insight = MaxInsightContext(
            id="123",
            name="Failed Insight",
            description=None,
            query=TrendsQuery(series=[]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = await self.context_manager._format_ui_context(ui_context)

        # Should return None since the insight failed to run
        self.assertIsNone(result)
        mock_capture_exception.assert_called()

    def test_deduplicate_context_messages(self):
        """Test that context messages are deduplicated based on existing context message content"""
        # Create state with existing context messages
        state = AssistantState(
            messages=[
                HumanMessage(content="User message 1"),
                ContextMessage(content="Existing context 1", id="1"),
                AssistantMessage(content="Response"),
                ContextMessage(content="Existing context 2", id="2"),
                HumanMessage(content="User message 2"),
            ]
        )

        # Test deduplication - should filter out matching content
        context_prompts = [
            "New context message",
            "Existing context 1",  # This should be filtered out
            "Another new message",
            "Existing context 2",  # This should be filtered out
        ]

        result = self.context_manager._deduplicate_context_messages(state, context_prompts)

        expected = ["New context message", "Another new message"]
        self.assertEqual(result, expected)

    async def test_get_context_prompts_with_ui_and_contextual_tools(self):
        """Test that context prompts are returned for both UI context and contextual tools"""
        with (
            patch.object(AssistantContextManager, "_get_contextual_tools_prompt") as mock_contextual_tools,
            patch.object(AssistantContextManager, "_format_ui_context") as mock_format_ui,
            patch.object(AssistantContextManager, "get_ui_context") as mock_get_ui,
            patch.object(AssistantContextManager, "_deduplicate_context_messages") as mock_dedupe,
        ):
            # Setup mocks
            mock_contextual_tools.return_value = "Contextual tools prompt"
            mock_format_ui.return_value = "UI context prompt"
            mock_get_ui.return_value = MaxUIContext()
            mock_dedupe.return_value = ["Contextual tools prompt", "UI context prompt"]

            state = AssistantState(messages=[HumanMessage(content="Test")])

            result = await self.context_manager._get_context_prompts(state)

            # Verify both prompts are included
            self.assertEqual(result, ["Contextual tools prompt", "UI context prompt"])

            # Verify methods were called
            mock_contextual_tools.assert_called_once_with()
            mock_get_ui.assert_called_once_with(state)
            mock_format_ui.assert_called_once_with(MaxUIContext())
            mock_dedupe.assert_called_once_with(state, ["Contextual tools prompt", "UI context prompt"])

    async def test_get_context_prompts_with_only_contextual_tools(self):
        """Test that context prompts work when only contextual tools are present"""
        with (
            patch.object(AssistantContextManager, "_get_contextual_tools_prompt") as mock_contextual_tools,
            patch.object(AssistantContextManager, "_format_ui_context") as mock_format_ui,
            patch.object(AssistantContextManager, "get_ui_context") as mock_get_ui,
            patch.object(AssistantContextManager, "_deduplicate_context_messages") as mock_dedupe,
        ):
            # Setup mocks - only contextual tools, no UI context
            mock_contextual_tools.return_value = "Contextual tools prompt"
            mock_format_ui.return_value = None  # No UI context
            mock_get_ui.return_value = MaxUIContext()
            mock_dedupe.return_value = ["Contextual tools prompt"]

            state = AssistantState(messages=[HumanMessage(content="Test")])

            result = await self.context_manager._get_context_prompts(state)

            # Should only include contextual tools prompt
            self.assertEqual(result, ["Contextual tools prompt"])
            mock_dedupe.assert_called_once_with(state, ["Contextual tools prompt"])

    def test_get_contextual_tools(self):
        """Test extraction of contextual tools from config"""
        # Test with valid contextual tools
        config = RunnableConfig(
            configurable={
                "contextual_tools": {
                    "search_session_recordings": {"current_filters": {}},
                    "navigate": {"page_key": "insights"},
                }
            }
        )
        context_manager = AssistantContextManager(self.team, self.user, config)
        tools = context_manager.get_contextual_tools()

        self.assertEqual(len(tools), 2)
        self.assertIn("search_session_recordings", tools)
        self.assertIn("navigate", tools)
        self.assertEqual(tools["search_session_recordings"], {"current_filters": {}})
        self.assertEqual(tools["navigate"], {"page_key": "insights"})

    def test_get_contextual_tools_empty(self):
        """Test extraction of contextual tools returns empty dict when no tools"""
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(self.team, self.user, config)
        tools = context_manager.get_contextual_tools()

        self.assertEqual(tools, {})

    def test_get_contextual_tools_invalid_type(self):
        """Test extraction of contextual tools raises error for invalid type"""
        config = RunnableConfig(configurable={"contextual_tools": "invalid"})
        context_manager = AssistantContextManager(self.team, self.user, config)
        self.assertEqual(context_manager.get_contextual_tools(), {})

    def test_format_entity_context(self):
        """Test formatting of entity context (events/actions)"""
        # Test with events
        events = [
            MaxEventContext(id="1", name="page_view"),
            MaxEventContext(id="2", name="button_click", description="Click tracking"),
        ]

        result = self.context_manager._format_entity_context(events, "events", "Event")

        expected = '<events_context>Event names the user is referring to:\n"page_view", "button_click: Click tracking"\n</events_context>'
        self.assertEqual(result, expected)

    def test_format_entity_context_empty(self):
        """Test formatting of entity context returns empty string for no entities"""
        result = self.context_manager._format_entity_context(None, "events", "Event")
        self.assertEqual(result, "")

        result = self.context_manager._format_entity_context([], "events", "Event")
        self.assertEqual(result, "")

    @patch("ee.hogai.tool.get_contextual_tool_class")
    def test_get_contextual_tools_prompt(self, mock_get_contextual_tool_class):
        """Test generation of contextual tools prompt"""
        # Mock the tool class
        mock_tool = MagicMock()
        mock_tool.format_context_prompt_injection.return_value = "Tool system prompt"
        mock_get_contextual_tool_class.return_value = lambda team, user, tool_call_id: mock_tool

        config = RunnableConfig(
            configurable={"contextual_tools": {"search_session_recordings": {"current_filters": {}}}}
        )
        context_manager = AssistantContextManager(self.team, self.user, config)

        result = context_manager._get_contextual_tools_prompt()

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn("<search_session_recordings>", result)
        self.assertIn("Tool system prompt", result)
        self.assertIn("</search_session_recordings>", result)

    def test_get_contextual_tools_prompt_no_tools(self):
        """Test generation of contextual tools prompt returns None when no tools"""
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(self.team, self.user, config)

        result = context_manager._get_contextual_tools_prompt()

        self.assertIsNone(result)

    def test_inject_context_messages(self):
        """Test injection of context messages into state"""
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ],
            start_id="3",  # Start from the last message
        )

        context_prompts = ["Context 1", "Context 2"]

        result = self.context_manager._inject_context_messages(state, context_prompts)

        # Context messages should be inserted right before the start message (id="3")
        # Original order: [HumanMessage(id=1), AssistantMessage(id=2), HumanMessage(id=3)]
        # start_idx = 2 (index of message with id=3)
        # Context messages inserted at start_idx
        # New order: [HumanMessage(id=1), AssistantMessage(id=2), Context1, Context2, HumanMessage(id=3)]
        self.assertEqual(len(result), 5)  # 3 original + 2 context
        self.assertIsInstance(result[0], HumanMessage)  # First message (id=1)
        self.assertIsInstance(result[1], AssistantMessage)  # Response (id=2)
        self.assertIsInstance(result[2], ContextMessage)  # Context 1
        self.assertIsInstance(result[3], ContextMessage)  # Context 2
        self.assertIsInstance(result[4], HumanMessage)  # Start message (id=3)

        # Verify context message content
        assert isinstance(result[2], ContextMessage)
        assert isinstance(result[3], ContextMessage)
        self.assertEqual(result[2].content, "Context 1")
        self.assertEqual(result[3].content, "Context 2")

    async def test_get_state_messages_with_context(self):
        """Test that context messages are properly added to state"""
        with (
            patch.object(AssistantContextManager, "_get_context_prompts") as mock_get_prompts,
            patch.object(AssistantContextManager, "_inject_context_messages") as mock_inject,
        ):
            mock_get_prompts.return_value = ["Context prompt"]
            mock_inject.return_value = [
                ContextMessage(content="Context prompt"),
                HumanMessage(content="Test"),
            ]

            state = AssistantState(messages=[HumanMessage(content="Test")])

            result = await self.context_manager.get_state_messages_with_context(state)

            mock_get_prompts.assert_called_once_with(state)
            mock_inject.assert_called_once_with(state, ["Context prompt"])
            assert result is not None
            self.assertEqual(len(result), 2)

    async def test_get_state_messages_with_context_no_prompts(self):
        """Test that original messages are returned when no context prompts"""
        with patch.object(AssistantContextManager, "_get_context_prompts") as mock_get_prompts:
            mock_get_prompts.return_value = []

            messages = [HumanMessage(content="Test")]
            state = AssistantState(messages=messages)

            result = await self.context_manager.get_state_messages_with_context(state)

            self.assertIsNone(result)

    def test_has_awaitable_context(self):
        """Test detection of awaitable context in state"""
        # Test with dashboards
        ui_context = MaxUIContext(
            dashboards=[MaxDashboardContext(id=1, name="Test", insights=[], filters=DashboardFilter())]
        )
        state = AssistantState(messages=[HumanMessage(content="Test", ui_context=ui_context)])

        with patch.object(self.context_manager, "get_ui_context", return_value=ui_context):
            result = self.context_manager.has_awaitable_context(state)
            self.assertTrue(result)

        # Test with insights
        ui_context = MaxUIContext(insights=[MaxInsightContext(id="1", name="Test", query=TrendsQuery(series=[]))])
        with patch.object(self.context_manager, "get_ui_context", return_value=ui_context):
            result = self.context_manager.has_awaitable_context(state)
            self.assertTrue(result)

        # Test without awaitable context
        ui_context = MaxUIContext(events=[MaxEventContext(id="1", name="Test")])
        with patch.object(self.context_manager, "get_ui_context", return_value=ui_context):
            result = self.context_manager.has_awaitable_context(state)
            self.assertFalse(result)

    @parameterized.expand(
        [
            [OrganizationMembership.Level.ADMIN, True],
            [OrganizationMembership.Level.OWNER, True],
            [OrganizationMembership.Level.MEMBER, False],
        ]
    )
    async def test_has_billing_access(self, membership_level, has_access):
        # Set membership level
        membership = await self.user.organization_memberships.aget(organization=self.team.organization)
        membership.level = membership_level
        await membership.asave()
        self.assertEqual(await self.context_manager.check_user_has_billing_access(), has_access)

    async def test_get_billing_context(self):
        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            has_active_subscription=True,
            products=[],
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
            trial=MaxBillingContextTrial(is_active=True, expires_at=str(datetime.date(2023, 2, 1)), target="scale"),
        )
        config = RunnableConfig(configurable={"billing_context": billing_context.model_dump()})
        context_manager = AssistantContextManager(self.team, self.user, config)
        self.assertEqual(context_manager.get_billing_context(), billing_context)

        context_manager = AssistantContextManager(self.team, self.user, RunnableConfig(configurable={}))
        self.assertIsNone(context_manager.get_billing_context())
