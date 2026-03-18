import datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantToolCall,
    ContextMessage,
    DashboardFilter,
    EntityType,
    EventsNode,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    MaxActionContext,
    MaxBillingContext,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
    MaxUIContext,
    ModeContext,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
)

from posthog.models.organization import OrganizationMembership

from ee.hogai.context import AssistantContextManager
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantMessageUnion


class TestAssistantContextManager(BaseTest):
    def setUp(self):
        super().setUp()
        self.config = RunnableConfig(configurable={})
        self.context_manager = AssistantContextManager(self.team, self.user, self.config)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_build_and_execute_insight_trends_query(self, mock_execute):
        mock_execute.return_value = "Trend results: 100 users"

        insight = MaxInsightContext(
            id="123",
            name="User Trends",
            description="Daily active users",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        insight_ctx = self.context_manager._build_insight_context(insight, dashboard_filters=None)
        result = await self.context_manager._execute_and_format_insight(insight_ctx)
        assert result is not None
        # Check the key parts of the result
        self.assertIn("## Name: User Trends", result)
        self.assertIn("Insight ID: 123", result)
        self.assertIn("Description: Daily active users", result)
        self.assertIn("TrendsQuery", result)
        self.assertIn("Trend results: 100 users", result)
        mock_execute.assert_called_once()

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_build_and_execute_insight_funnel_query(self, mock_execute):
        mock_execute.return_value = "Funnel results: 50% conversion"

        insight = MaxInsightContext(
            id="456",
            name="Conversion Funnel",
            description=None,
            query=FunnelsQuery(series=[EventsNode(event="sign_up"), EventsNode(event="purchase")]),
        )

        insight_ctx = self.context_manager._build_insight_context(insight, dashboard_filters=None)
        result = await self.context_manager._execute_and_format_insight(insight_ctx)
        assert result is not None
        # Check the key parts of the result
        self.assertIn("## Name: Conversion Funnel", result)
        self.assertIn("Insight ID: 456", result)
        self.assertIn("FunnelsQuery", result)
        self.assertIn("Funnel results: 50% conversion", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_build_and_execute_insight_retention_query(self, mock_execute):
        mock_execute.return_value = "Retention: 30% Day 7"

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

        insight_ctx = self.context_manager._build_insight_context(insight, dashboard_filters=None)
        result = await self.context_manager._execute_and_format_insight(insight_ctx)
        assert result is not None
        # Check the key parts of the result
        self.assertIn("## Name: Insight", result)  # Falls back to "Insight" when no name
        self.assertIn("Insight ID: 789", result)
        self.assertIn("RetentionQuery", result)
        self.assertIn("Retention: 30% Day 7", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_build_and_execute_insight_hogql_query(self, mock_execute):
        mock_execute.return_value = "Query results: 42 events"

        insight = MaxInsightContext(
            id="101",
            name="Custom Query",
            description="HogQL analysis",
            query=HogQLQuery(query="SELECT count() FROM events"),
        )

        insight_ctx = self.context_manager._build_insight_context(insight, dashboard_filters=None)
        result = await self.context_manager._execute_and_format_insight(insight_ctx)
        assert result is not None
        # Check the key parts of the result
        self.assertIn("## Name: Custom Query", result)
        self.assertIn("Insight ID: 101", result)
        self.assertIn("Description: HogQL analysis", result)
        self.assertIn("HogQLQuery", result)
        self.assertIn("Query results: 42 events", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    @patch("ee.hogai.context.context.capture_exception")
    async def test_execute_and_format_insight_exception_handling(self, mock_capture_exception, mock_execute):
        mock_execute.side_effect = Exception("Query failed")

        insight = MaxInsightContext(
            id="123",
            name="Failed Query",
            description=None,
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        insight_ctx = self.context_manager._build_insight_context(insight, dashboard_filters=None)
        result = await self.context_manager._execute_and_format_insight(insight_ctx)

        self.assertEqual(result, None)
        mock_capture_exception.assert_called_once()

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_format_ui_context_with_dashboard(self, mock_execute):
        mock_execute.return_value = "Dashboard insight results"

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
        self.assertIn("## Dashboard name: Test Dashboard", result)
        self.assertIn("Description: Test dashboard description", result)
        self.assertIn("Dashboard insights:", result)
        # The insight execution is tested separately - just verify structure here
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

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_format_ui_context_with_standalone_insights(self, mock_execute):
        mock_execute.return_value = "Standalone insight results"

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
        self.assertIn("Name: Standalone Insight", result)  # Uses "Name:" not "Insight:"
        self.assertIn("Standalone insight results", result)
        self.assertNotIn("# Dashboards", result)

    async def test_format_ui_context_empty(self):
        result = await self.context_manager._format_ui_context(None)
        self.assertIsNone(result)

        # Test with ui_context but no insights
        ui_context = MaxUIContext(insights=None)
        result = await self.context_manager._format_ui_context(ui_context)
        self.assertIsNone(result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_format_ui_context_with_insights(self, mock_execute):
        mock_execute.return_value = "Insight execution results"

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

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    @patch("ee.hogai.context.context.capture_exception")
    async def test_format_ui_context_with_failed_insights(self, mock_capture_exception, mock_execute):
        mock_execute.side_effect = Exception("Query failed")

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
        context_messages = [
            ContextMessage(content="New context message", id="new1"),
            ContextMessage(content="Existing context 1", id="dup1"),  # This should be filtered out
            ContextMessage(content="Another new message", id="new2"),
            ContextMessage(content="Existing context 2", id="dup2"),  # This should be filtered out
        ]

        result = self.context_manager._deduplicate_context_messages(state, context_messages)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].content, "New context message")
        self.assertEqual(result[1].content, "Another new message")

    async def test_get_context_messages_with_ui_and_contextual_tools(self):
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
            ctx_tools_msg = ContextMessage(content="Contextual tools prompt", id="1")
            ui_context_msg = ContextMessage(content="UI context prompt", id="2")
            mock_dedupe.return_value = [ctx_tools_msg, ui_context_msg]

            state = AssistantState(messages=[HumanMessage(content="Test")])

            result = await self.context_manager._get_context_messages(state)

            # Verify both prompts are included
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0].content, "Contextual tools prompt")
            self.assertEqual(result[1].content, "UI context prompt")

            # Verify methods were called
            mock_contextual_tools.assert_called_once_with()
            mock_get_ui.assert_called_once_with(state)
            mock_format_ui.assert_called_once_with(MaxUIContext())

    async def test_get_context_messages_with_only_contextual_tools(self):
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
            ctx_tools_msg = ContextMessage(content="Contextual tools prompt", id="1")
            mock_dedupe.return_value = [ctx_tools_msg]

            state = AssistantState(messages=[HumanMessage(content="Test")])

            result = await self.context_manager._get_context_messages(state)

            # Should only include contextual tools prompt
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].content, "Contextual tools prompt")

    def test_get_contextual_tools(self):
        """Test extraction of contextual tools from config"""
        # Test with valid contextual tools
        config = RunnableConfig(
            configurable={
                "contextual_tools": {
                    "search_session_recordings": {"current_filters": {}},
                }
            }
        )
        context_manager = AssistantContextManager(self.team, self.user, config)
        tools = context_manager.get_contextual_tools()

        self.assertEqual(len(tools), 1)
        self.assertIn("search_session_recordings", tools)
        self.assertEqual(tools["search_session_recordings"], {"current_filters": {}})

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

    async def test_get_contextual_tools_prompt(self):
        """Test generation of contextual tools prompt"""
        config = RunnableConfig(
            configurable={
                "contextual_tools": {"search_session_recordings": {"current_filters": {}, "current_session_id": None}}
            }
        )
        context_manager = AssistantContextManager(self.team, self.user, config)

        result = await context_manager._get_contextual_tools_prompt()
        assert result is not None
        self.assertIn("<search_session_recordings>", result)
        self.assertIn("Current recordings filters are", result)
        self.assertIn("Current session ID being viewed", result)
        self.assertIn("</search_session_recordings>", result)

    async def test_get_contextual_tools_prompt_no_tools(self):
        """Test generation of contextual tools prompt returns None when no tools"""
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(self.team, self.user, config)

        result = await context_manager._get_contextual_tools_prompt()

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

        context_messages = [
            ContextMessage(content="Context 1", id="ctx1"),
            ContextMessage(content="Context 2", id="ctx2"),
        ]

        result = self.context_manager._inject_context_messages(state, context_messages)

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
            patch.object(AssistantContextManager, "_get_context_messages") as mock_get_prompts,
            patch.object(AssistantContextManager, "_inject_context_messages") as mock_inject,
        ):
            ctx_msg = ContextMessage(content="Context prompt", id="ctx1")
            mock_get_prompts.return_value = [ctx_msg]
            mock_inject.return_value = [
                ContextMessage(content="Context prompt"),
                HumanMessage(content="Test"),
            ]

            state = AssistantState(messages=[HumanMessage(content="Test")])

            result = await self.context_manager.get_state_messages_with_context(state)

            mock_get_prompts.assert_called_once_with(state)
            mock_inject.assert_called_once_with(state, [ctx_msg])
            assert result is not None
            self.assertEqual(len(result), 2)

    async def test_get_state_messages_with_context_no_prompts(self):
        """Test that original messages are returned when no context prompts"""
        with patch.object(AssistantContextManager, "_get_context_messages") as mock_get_prompts:
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

    async def test_get_context_messages_with_agent_mode_at_start(self):
        """Test that mode prompt is added when feature flag is enabled and message is at start"""
        state = AssistantState(
            messages=[HumanMessage(content="Test", id="1")],
            start_id="1",
            agent_mode=AgentMode.PRODUCT_ANALYTICS,
        )

        result = await self.context_manager.get_state_messages_with_context(state)

        assert result is not None
        self.assertEqual(len(result), 2)
        assert isinstance(result[0], ContextMessage)
        self.assertIn("Your initial mode is", result[0].content)
        self.assertIn("product_analytics", result[0].content)
        # Verify metadata is set correctly
        assert isinstance(result[0].meta, ModeContext)
        self.assertEqual(result[0].meta.mode, AgentMode.PRODUCT_ANALYTICS)
        self.assertIsInstance(result[1], HumanMessage)

    async def test_get_context_messages_with_agent_mode_switch(self):
        """Test that mode switch prompt is added when mode changes mid-conversation"""
        state = AssistantState(
            messages=[
                ContextMessage(
                    content="<system_reminder>Your initial mode is product_analytics.</system_reminder>",
                    id="0",
                    meta=ModeContext(mode=AgentMode.PRODUCT_ANALYTICS),
                ),
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ],
            start_id="3",
            agent_mode=AgentMode.SQL,  # Mode changed from product_analytics to SQL
        )

        result = await self.context_manager.get_state_messages_with_context(state)

        assert result is not None
        # Should have added a mode switch context message before the start message
        self.assertEqual(len(result), 5)
        assert isinstance(result[3], ContextMessage)
        self.assertIn("Your mode has been switched to", result[3].content)
        self.assertIn("sql", result[3].content)
        # Verify metadata is set correctly
        assert isinstance(result[3].meta, ModeContext)
        self.assertEqual(result[3].meta.mode, AgentMode.SQL)

    async def test_get_context_messages_no_mode_switch_when_same_mode(self):
        """Test that no mode prompt is added when mode hasn't changed"""
        state = AssistantState(
            messages=[
                ContextMessage(
                    content="<system_reminder>Your initial mode is product_analytics.</system_reminder>",
                    id="0",
                    meta=ModeContext(mode=AgentMode.PRODUCT_ANALYTICS),
                ),
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ],
            start_id="3",
            agent_mode=AgentMode.PRODUCT_ANALYTICS,  # Same mode as initial
        )

        result = await self.context_manager.get_state_messages_with_context(state)

        # Should return None since no context needs to be added
        self.assertIsNone(result)

    def test_get_previous_mode_from_messages_initial(self):
        """Test extraction of initial mode from context messages via metadata"""
        messages: list[AssistantMessageUnion] = [
            ContextMessage(
                content="<system_reminder>Your initial mode is sql.</system_reminder>",
                id="0",
                meta=ModeContext(mode=AgentMode.SQL),
            ),
            HumanMessage(content="Test", id="1"),
        ]

        result = self.context_manager._get_previous_mode_from_messages(messages)

        self.assertEqual(result, AgentMode.SQL)

    def test_get_previous_mode_from_messages_switched(self):
        """Test extraction of switched mode from context messages via metadata"""
        messages: list[AssistantMessageUnion] = [
            ContextMessage(
                content="<system_reminder>Your initial mode is product_analytics.</system_reminder>",
                id="0",
                meta=ModeContext(mode=AgentMode.PRODUCT_ANALYTICS),
            ),
            HumanMessage(content="First message", id="1"),
            ContextMessage(
                content="<system_reminder>Your mode has been switched to sql.</system_reminder>",
                id="2",
                meta=ModeContext(mode=AgentMode.SQL),
            ),
            HumanMessage(content="Second message", id="3"),
        ]

        # Should return the most recent mode (sql, from the switch)
        result = self.context_manager._get_previous_mode_from_messages(messages)

        self.assertEqual(result, AgentMode.SQL)

    def test_get_previous_mode_from_messages_switch_mode_tool_call(self):
        """Test extraction of mode from switch_mode tool call"""
        messages: list[AssistantMessageUnion] = [
            ContextMessage(
                content="<system_reminder>Your initial mode is product_analytics.</system_reminder>", id="0"
            ),
            HumanMessage(content="First message", id="1"),
            AssistantMessage(
                content="Switching to SQL mode",
                id="2",
                tool_calls=[AssistantToolCall(id="tc1", name="switch_mode", args={"new_mode": "sql"})],
            ),
            HumanMessage(content="Second message", id="3"),
        ]

        # Should return sql from the switch_mode tool call
        result = self.context_manager._get_previous_mode_from_messages(messages)

        self.assertEqual(result, AgentMode.SQL)

    def test_get_previous_mode_from_messages_no_mode(self):
        """Test extraction returns None when no mode context exists"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Test", id="1"),
            AssistantMessage(content="Response", id="2"),
        ]

        result = self.context_manager._get_previous_mode_from_messages(messages)

        self.assertIsNone(result)

    def test_create_mode_context_message_initial(self):
        """Test creation of initial mode context message"""
        result = self.context_manager._create_mode_context_message(AgentMode.PRODUCT_ANALYTICS, is_initial=True)

        self.assertIsInstance(result, ContextMessage)
        self.assertIn("Your initial mode is", result.content)
        self.assertIn("product_analytics", result.content)
        assert isinstance(result.meta, ModeContext)
        self.assertEqual(result.meta.mode, AgentMode.PRODUCT_ANALYTICS)

    def test_create_mode_context_message_switch(self):
        """Test creation of mode switch context message"""
        result = self.context_manager._create_mode_context_message(AgentMode.SQL, is_initial=False)

        self.assertIsInstance(result, ContextMessage)
        self.assertIn("Your mode has been switched to", result.content)
        self.assertIn("sql", result.content)
        assert isinstance(result.meta, ModeContext)
        self.assertEqual(result.meta.mode, AgentMode.SQL)
