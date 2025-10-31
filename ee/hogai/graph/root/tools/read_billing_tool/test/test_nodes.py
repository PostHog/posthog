import datetime
from typing import cast
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    BillingSpendResponseBreakdownType,
    BillingUsageResponseBreakdownType,
    MaxAddonInfo,
    MaxBillingContext,
    MaxBillingContextBillingPeriod,
    MaxBillingContextBillingPeriodInterval,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
    MaxProductInfo,
    SpendHistoryItem,
    UsageHistoryItem,
)

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.root.tools.read_billing_tool.tool import ReadBillingTool
from ee.hogai.utils.types import AssistantState


class TestBillingNode(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ReadBillingTool(
            team=self.team,
            user=self.user,
            node_path=(),
            state=AssistantState(messages=[], root_tool_call_id=str(uuid4())),
            config=RunnableConfig(configurable={}),
            context_manager=AssistantContextManager(self.team, self.user, {}),
        )

    async def test_run_with_no_billing_context(self):
        with patch.object(self.tool._context_manager, "get_billing_context", return_value=None):
            result = await self.tool.execute()
            self.assertEqual(result, "No billing information available")

    async def test_run_with_billing_context(self):
        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            billing_plan="paid",
            has_active_subscription=True,
            is_deactivated=False,
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=2),
            products=[],
        )
        with (
            patch.object(self.tool._context_manager, "get_billing_context", return_value=billing_context),
            patch.object(self.tool, "_format_billing_context", return_value="Formatted Context"),
        ):
            result = await self.tool.execute()
            self.assertEqual(result, "Formatted Context")

    async def test_format_billing_context(self):
        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            billing_plan="paid",
            has_active_subscription=True,
            is_deactivated=False,
            billing_period=MaxBillingContextBillingPeriod(
                current_period_start=str(datetime.date(2023, 1, 1)),
                current_period_end=str(datetime.date(2023, 1, 31)),
                interval=MaxBillingContextBillingPeriodInterval.MONTH,
            ),
            total_current_amount_usd="100.00",
            products=[
                MaxProductInfo(
                    name="Product A",
                    type="type_a",
                    description="Desc A",
                    current_usage=50,
                    usage_limit=100,
                    percentage_usage=0.5,
                    has_exceeded_limit=False,
                    is_used=True,
                    addons=[],
                )
            ],
            trial=MaxBillingContextTrial(is_active=True, expires_at=str(datetime.date(2023, 2, 1)), target="scale"),
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=2),
        )

        with patch.object(self.tool, "_get_top_events_by_usage", return_value=[]):
            formatted_string = await self.tool._format_billing_context(billing_context)
            self.assertIn("(paid)", formatted_string)
            self.assertIn("Period: 2023-01-01 to 2023-01-31", formatted_string)

    def test_format_history_table(self):
        usage_history = [
            UsageHistoryItem(
                id=1,
                label="Recordings",
                dates=["2023-01-01", "2023-01-02"],
                data=[100, 200],
                breakdown_type=BillingUsageResponseBreakdownType.TYPE,
                breakdown_value=["recording_count_in_period"],
            ),
            UsageHistoryItem(
                id=2,
                label="Events",
                dates=["2023-01-01", "2023-01-02"],
                data=[1.5, 2.5],
                breakdown_type=BillingUsageResponseBreakdownType.TYPE,
                breakdown_value=["event_count_in_period"],
            ),
        ]
        spend_history = [
            SpendHistoryItem(
                id=1,
                label="Mobile Recordings",
                dates=["2023-01-01", "2023-01-02"],
                data=[10.50, 20.00],
                breakdown_type=None,
            ),
        ]

        usage_table = self.tool._format_history_table(usage_history)
        self.assertIn("### Overall (all projects)", usage_table)
        self.assertIn("| Data Type | 2023-01-01 | 2023-01-02 |", usage_table)
        self.assertIn("| Recordings | 100.00 | 200.00 |", usage_table)
        self.assertIn("| Events | 1.50 | 2.50 |", usage_table)

        spend_table = self.tool._format_history_table(spend_history)
        self.assertIn("| Mobile Recordings | 10.50 | 20.00 |", spend_table)

    def test_get_top_events_by_usage(self):
        mock_results = [("pageview", 1000), ("$autocapture", 500)]
        with patch(
            "ee.hogai.graph.root.tools.read_billing_tool.tool.sync_execute", return_value=mock_results
        ) as mock_sync_execute:
            top_events = self.tool._get_top_events_by_usage()
            self.assertEqual(len(top_events), 2)
            self.assertEqual(top_events[0]["event"], "pageview")
            self.assertEqual(top_events[0]["count"], 1000)
            self.assertEqual(top_events[0]["formatted_count"], "1,000")
            self.assertEqual(top_events[1]["event"], "$autocapture")
            self.assertEqual(top_events[1]["count"], 500)
            self.assertEqual(top_events[1]["formatted_count"], "500")

            mock_sync_execute.assert_called_once()
            # Check team_id is passed correctly
            self.assertIn(str(self.team.pk), str(mock_sync_execute.call_args))

    def test_get_top_events_by_usage_query_fails(self):
        with patch(
            "ee.hogai.graph.root.tools.read_billing_tool.tool.sync_execute",
            side_effect=Exception("DB connection failed"),
        ) as mock_sync_execute:
            top_events = self.tool._get_top_events_by_usage()
            self.assertEqual(top_events, [])
            mock_sync_execute.assert_called_once()

    async def test_format_billing_context_with_addons(self):
        """Test that addons are properly nested within products in the formatted output"""
        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            billing_plan="startup",
            has_active_subscription=True,
            is_deactivated=False,
            startup_program_label="YC W21",
            billing_period=MaxBillingContextBillingPeriod(
                current_period_start="2023-01-01",
                current_period_end="2023-01-31",
                interval=MaxBillingContextBillingPeriodInterval.MONTH,
            ),
            total_current_amount_usd="500.00",
            projected_total_amount_usd="1000.00",
            projected_total_amount_usd_after_discount="900.00",
            projected_total_amount_usd_with_limit="800.00",
            projected_total_amount_usd_with_limit_after_discount="700.00",
            products=[
                MaxProductInfo(
                    name="Product Analytics",
                    type="analytics",
                    description="Track and analyze product metrics",
                    current_usage=50000,
                    usage_limit=100000,
                    percentage_usage=0.5,
                    has_exceeded_limit=False,
                    is_used=True,
                    custom_limit_usd=500.0,
                    next_period_custom_limit_usd=600.0,
                    projected_amount_usd="400.0",
                    projected_amount_usd_with_limit="350.0",
                    docs_url="https://posthog.com/docs/product-analytics",
                    addons=[
                        MaxAddonInfo(
                            name="Group Analytics",
                            type="addon",
                            description="Analyze by groups",
                            current_usage=1000.0,
                            usage_limit=5000,
                            has_exceeded_limit=False,
                            is_used=True,
                            percentage_usage=0.2,
                            projected_amount_usd="50.0",
                            docs_url="https://posthog.com/docs/group-analytics",
                        ),
                        MaxAddonInfo(
                            name="Data Pipelines",
                            type="addon",
                            description="Export data to destinations",
                            current_usage=2000.0,
                            has_exceeded_limit=False,
                            is_used=True,
                            projected_amount_usd="100.0",
                        ),
                    ],
                ),
                MaxProductInfo(
                    name="Session Replay",
                    type="replay",
                    description="Record and replay user sessions",
                    current_usage=1000,
                    usage_limit=5000,
                    percentage_usage=0.2,
                    has_exceeded_limit=False,
                    is_used=True,
                    addons=[],
                ),
            ],
            trial=None,
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=3),
        )

        with patch.object(
            self.tool,
            "_get_top_events_by_usage",
            return_value=[
                {"event": "$pageview", "count": 50000, "formatted_count": "50,000"},
                {"event": "$autocapture", "count": 30000, "formatted_count": "30,000"},
            ],
        ):
            formatted_string = await self.tool._format_billing_context(billing_context)

            # Check basic info
            self.assertIn("paid subscription (startup)", formatted_string)
            self.assertIn("Startup program: YC W21", formatted_string)

            # Check billing period
            self.assertIn("Period: 2023-01-01 to 2023-01-31", formatted_string)

            # Check cost projections with corrected field names
            self.assertIn("Current period cost: $500.00", formatted_string)
            self.assertIn("Projected period cost: $1000.00", formatted_string)
            self.assertIn("Projected period cost after discount: $900.00", formatted_string)
            self.assertIn("Projected period cost with spending limit: $800.00", formatted_string)
            self.assertIn("Projected period cost with spending limit after discount: $700.00", formatted_string)

            # Check products
            self.assertIn("### Product Analytics", formatted_string)
            self.assertIn("Current usage: 50000 of 100000 limit", formatted_string)
            self.assertIn("Custom spending limit: $500.0", formatted_string)
            self.assertIn("Next period custom spending limit: $600.0", formatted_string)

            # Check addons are nested within products
            self.assertIn("#### Add-ons for Product Analytics", formatted_string)
            self.assertIn("##### Group Analytics", formatted_string)
            self.assertIn("Current usage: 1000 of 5000 limit", formatted_string)
            self.assertIn("##### Data Pipelines", formatted_string)

            # Check Session Replay exists but has no addons section
            self.assertIn("### Session Replay", formatted_string)
            # Since Session Replay has empty addons array, no add-ons section should appear
            self.assertNotIn("#### Add-ons for Session Replay", formatted_string)

            # Check top events
            self.assertIn("$pageview", formatted_string)
            self.assertIn("50,000 events", formatted_string)

    async def test_format_billing_context_no_subscription(self):
        """Test formatting when user has no active subscription (free plan)"""
        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.FREE,
            billing_plan=None,
            has_active_subscription=False,
            is_deactivated=False,
            products=[],
            settings=MaxBillingContextSettings(autocapture_on=False, active_destinations=0),
            trial=MaxBillingContextTrial(is_active=True, expires_at="2023-02-01", target="teams"),
        )

        with patch.object(self.tool, "_get_top_events_by_usage", return_value=[]):
            formatted_string = await self.tool._format_billing_context(billing_context)

            self.assertIn("free subscription", formatted_string)
            self.assertIn("Active subscription: No (Free plan)", formatted_string)
            self.assertIn("Active trial", formatted_string)
            self.assertIn("expires: 2023-02-01", formatted_string)

    def test_format_history_table_with_team_breakdown(self):
        """Test that history tables properly group by team when breakdown includes team IDs"""
        # Mock the teams map
        self.tool._teams_map = {
            1: "Team Alpha (ID: 1)",
            2: "Team Beta (ID: 2)",
        }

        usage_history = [
            UsageHistoryItem(
                id=1,
                label="event_count_in_period",
                dates=["2023-01-01", "2023-01-02"],
                data=[1000, 2000],
                breakdown_type=BillingUsageResponseBreakdownType.TEAM,
                breakdown_value=["1"],  # Team ID 1
            ),
            UsageHistoryItem(
                id=2,
                label="recording_count_in_period",
                dates=["2023-01-01", "2023-01-02"],
                data=[100, 200],
                breakdown_type=BillingUsageResponseBreakdownType.TEAM,
                breakdown_value=["1"],  # Team ID 1
            ),
            UsageHistoryItem(
                id=3,
                label="event_count_in_period",
                dates=["2023-01-01", "2023-01-02"],
                data=[500, 750],
                breakdown_type=BillingUsageResponseBreakdownType.TEAM,
                breakdown_value=["2"],  # Team ID 2
            ),
            UsageHistoryItem(
                id=4,
                label="billable_feature_flag_requests_count_in_period",
                dates=["2023-01-01", "2023-01-02"],
                data=[50, 100],
                breakdown_type=BillingUsageResponseBreakdownType.TEAM,
                breakdown_value=None,  # No team breakdown
            ),
        ]

        table = self.tool._format_history_table(usage_history)

        # Check team-specific tables
        self.assertIn("### Team Alpha (ID: 1)", table)
        self.assertIn("### Team Beta (ID: 2)", table)
        self.assertIn("### Overall (all projects)", table)

        # Check data is properly grouped
        self.assertIn("| Events | 1,000.00 | 2,000.00 |", table)
        self.assertIn("| Recordings | 100.00 | 200.00 |", table)
        self.assertIn("| Feature Flag Requests | 50.00 | 100.00 |", table)

    async def test_format_billing_context_edge_cases(self):
        """Test edge cases and potential security issues"""
        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.CUSTOM,
            billing_plan="enterprise",
            has_active_subscription=True,
            is_deactivated=True,  # Deactivated account
            startup_program_label=None,
            startup_program_label_previous="YC W20",  # Previous program but no current
            products=[
                MaxProductInfo(
                    name="Product <script>alert('xss')</script>",  # XSS attempt in name
                    type="malicious",
                    description="Desc with }} mustache {{injection",  # Mustache injection attempt
                    current_usage=None,  # No usage
                    usage_limit=None,  # No limit
                    percentage_usage=1.5,  # Over 100%
                    has_exceeded_limit=True,
                    is_used=False,
                    addons=[],
                ),
            ],
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
        )

        with patch.object(self.tool, "_get_top_events_by_usage", return_value=[]):
            formatted_string = await self.tool._format_billing_context(billing_context)

            # Check deactivated status
            self.assertIn("Status: Account is deactivated", formatted_string)

            # Check previous startup program
            self.assertIn("Previous startup program: YC W20", formatted_string)

            # Check XSS attempts are properly escaped
            self.assertIn("Product &lt;script&gt;alert('xss')&lt;/script&gt;", formatted_string)
            self.assertIn("Desc with }} mustache {{injection", formatted_string)

            # Check None values are handled - when current_usage is None, it shows empty
            self.assertIn("Current usage:  (1.5% of limit)", formatted_string)

            # Check exceeded limit warning
            self.assertIn("⚠️ Usage limit exceeded", formatted_string)

    async def test_format_billing_context_complete_template_coverage(self):
        """Test all possible template variables are covered"""
        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            billing_plan="scale",
            has_active_subscription=True,
            is_deactivated=False,
            startup_program_label="Techstars 2023",
            startup_program_label_previous=None,
            billing_period=MaxBillingContextBillingPeriod(
                current_period_start="2023-01-01",
                current_period_end="2023-01-31",
                interval=MaxBillingContextBillingPeriodInterval.YEAR,
            ),
            total_current_amount_usd="5000.00",
            projected_total_amount_usd="10000.00",
            projected_total_amount_usd_after_discount="9000.00",
            projected_total_amount_usd_with_limit="8000.00",
            projected_total_amount_usd_with_limit_after_discount="7200.00",
            products=[
                MaxProductInfo(
                    name="Feature Flags",
                    type="flags",
                    description="Control feature rollouts",
                    current_usage=100000,
                    usage_limit=500000,
                    percentage_usage=0.2,
                    has_exceeded_limit=False,
                    is_used=True,
                    custom_limit_usd=1000.0,
                    next_period_custom_limit_usd=1500.0,
                    projected_amount_usd="800.0",
                    projected_amount_usd_with_limit="750.0",
                    docs_url="https://posthog.com/docs/feature-flags",
                    addons=[
                        MaxAddonInfo(
                            name="Local Evaluation",
                            type="addon",
                            description="Evaluate flags locally",
                            current_usage=50000.0,
                            usage_limit=100000,
                            has_exceeded_limit=False,
                            is_used=True,
                            percentage_usage=0.5,
                            projected_amount_usd="200.0",
                            docs_url="https://posthog.com/docs/feature-flags/local-evaluation",
                        ),
                    ],
                ),
            ],
            trial=MaxBillingContextTrial(
                is_active=False,
                expires_at="2022-12-31",
                target="enterprise",
            ),
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=5),
            usage_history=[
                UsageHistoryItem(
                    id=1,
                    label="event_count_in_period",
                    dates=["2023-01-29", "2023-01-30", "2023-01-31"],
                    data=[1000, 1500, 2000],
                    breakdown_type=BillingUsageResponseBreakdownType.TEAM,
                    breakdown_value=["1"],
                ),
            ],
            spend_history=[
                SpendHistoryItem(
                    id=1,
                    label="event_count_in_period",
                    dates=["2023-01-29", "2023-01-30", "2023-01-31"],
                    data=[50.0, 75.0, 100.0],
                    breakdown_type=BillingSpendResponseBreakdownType.TEAM,
                    breakdown_value=["1"],
                ),
            ],
        )

        # Mock teams map for history table
        self.tool._teams_map = {1: "Main Team (ID: 1)"}

        with patch.object(
            self.tool,
            "_get_top_events_by_usage",
            return_value=[{"event": "$identify", "count": 10000, "formatted_count": "10,000"}],
        ):
            formatted_string = await self.tool._format_billing_context(billing_context)

            # Verify all template sections are present
            self.assertIn("<billing_context>", formatted_string)
            self.assertIn("</billing_context>", formatted_string)
            self.assertIn("<organization_billing_info>", formatted_string)
            self.assertIn("</organization_billing_info>", formatted_string)
            self.assertIn("<products_info>", formatted_string)
            self.assertIn("</products_info>", formatted_string)
            self.assertIn("<usage_history_table>", formatted_string)
            self.assertIn("</usage_history_table>", formatted_string)
            self.assertIn("<spend_history_table>", formatted_string)
            self.assertIn("</spend_history_table>", formatted_string)
            self.assertIn("<settings>", formatted_string)
            self.assertIn("</settings>", formatted_string)
            self.assertIn("<top_events_for_current_project>", formatted_string)
            self.assertIn("</top_events_for_current_project>", formatted_string)
            self.assertIn("<cost_reduction_strategies>", formatted_string)
            self.assertIn("</cost_reduction_strategies>", formatted_string)
            self.assertIn("<upselling>", formatted_string)
            self.assertIn("</upselling>", formatted_string)

            # Check yearly interval
            self.assertIn("(yearly billing)", formatted_string)

            # Check settings values
            self.assertIn("Autocapture: True", formatted_string)
            self.assertIn("Active destinations: 5", formatted_string)

    def test_format_history_table_real_data_structure(self):
        """Test with realistic data structure matching production format"""
        usage_history = [
            UsageHistoryItem(
                id=1,
                label="84444::Data Pipelines",
                dates=["2025-02-01", "2025-02-02", "2025-02-03"],
                data=[8036.0, 10286.0, 8174.0],
                breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                breakdown_value=["data_pipelines", "84444"],
            ),
            UsageHistoryItem(
                id=2,
                label="12345::Events",
                dates=["2025-02-01", "2025-02-02", "2025-02-03"],
                data=[50000.0, 75000.0, 60000.0],
                breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                breakdown_value=["event_count_in_period", "12345"],
            ),
            UsageHistoryItem(
                id=3,
                label="84444::Events",
                dates=["2025-02-01", "2025-02-02", "2025-02-03"],
                data=[25000.0, 30000.0, 28000.0],
                breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                breakdown_value=["event_count_in_period", "84444"],
            ),
            UsageHistoryItem(
                id=4,
                label="global_feature_flags",
                dates=["2025-02-01", "2025-02-02", "2025-02-03"],
                data=[1000.0, 1500.0, 1200.0],
                breakdown_type=BillingUsageResponseBreakdownType.TYPE,
                breakdown_value=["billable_feature_flag_requests_count_in_period"],
            ),
        ]

        self.tool._teams_map = {
            84444: "Project 84444",
            12345: "Project 12345",
        }

        table = self.tool._format_history_table(usage_history)

        # Should always include aggregated table first
        self.assertIn("### Overall (all projects)", table)

        # Should include team-specific tables
        self.assertIn("### Project 84444", table)
        self.assertIn("### Project 12345", table)

        # Check aggregated data sums correctly
        # Events: 50000+25000=75000, 75000+30000=105000, 60000+28000=88000
        self.assertIn("| Events | 75,000.00 | 105,000.00 | 88,000.00 |", table)

        # Feature Flag Requests should appear in aggregated (only non-team data)
        self.assertIn("| Feature Flag Requests | 1,000.00 | 1,500.00 | 1,200.00 |", table)

        # Data Pipelines should show aggregated total (only from team 84444)
        self.assertIn("| Data Pipelines (deprecated) | 8,036.00 | 10,286.00 | 8,174.00 |", table)

        # Check that team-specific tables show clean labels
        # Team 84444 should show "Data Pipelines (deprecated)" and "Events", not raw labels
        team_84444_section = table.split("### Project 84444")[1].split("### Project 12345")[0]
        self.assertIn("| Data Pipelines (deprecated) |", team_84444_section)
        self.assertIn("| Events |", team_84444_section)
        self.assertNotIn("| 84444::", team_84444_section)  # Should not show raw labels

    def test_format_history_table_mixed_known_unknown_types(self):
        """Test with mix of known usage types and unknown custom types"""
        usage_history = [
            UsageHistoryItem(
                id=1,
                label="custom_product_12345",
                dates=["2025-02-01", "2025-02-02"],
                data=[100.0, 200.0],
                breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                breakdown_value=["unknown_type", "12345"],
            ),
            UsageHistoryItem(
                id=2,
                label="recordings_team_456",
                dates=["2025-02-01", "2025-02-02"],
                data=[50.0, 75.0],
                breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                breakdown_value=["recording_count_in_period", "456"],
            ),
        ]

        table = self.tool._format_history_table(usage_history)

        # Should include aggregated table
        self.assertIn("### Overall (all projects)", table)

        # Should handle known types correctly
        self.assertIn("| Recordings | 50.00 | 75.00 |", table)

        # Should handle unknown types gracefully (formatted from label)
        self.assertIn("| Custom Product 12345 | 100.00 | 200.00 |", table)

    def test_create_aggregated_items_functionality(self):
        """Test the aggregation logic specifically"""
        # Create test data with overlapping dates
        team_items = {
            "12345": [
                UsageHistoryItem(
                    id=1,
                    label="events",
                    dates=["2025-02-01", "2025-02-02"],
                    data=[1000, 2000],
                    breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                    breakdown_value=["event_count_in_period", "12345"],
                )
            ],
            "67890": [
                UsageHistoryItem(
                    id=2,
                    label="events",
                    dates=["2025-02-02", "2025-02-03"],  # Overlapping dates
                    data=[1500, 2500],
                    breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                    breakdown_value=["event_count_in_period", "67890"],
                )
            ],
        }

        other_items = [
            UsageHistoryItem(
                id=3,
                label="global_flags",
                dates=["2025-02-01", "2025-02-03"],
                data=[100, 300],
                breakdown_type=BillingUsageResponseBreakdownType.TYPE,
                breakdown_value=["billable_feature_flag_requests_count_in_period"],
            )
        ]

        aggregated = self.tool._create_aggregated_items(team_items, other_items)

        # Should have 2 aggregated items: events and feature flags
        self.assertEqual(len(aggregated), 2)

        # Find the events aggregated item
        events_item = next((item for item in aggregated if "Events" in item.label), None)
        self.assertIsNotNone(events_item)

        events_item = cast(UsageHistoryItem, events_item)
        # Should have all 3 unique dates
        self.assertEqual(len(events_item.dates), 3)
        self.assertEqual(events_item.dates, ["2025-02-01", "2025-02-02", "2025-02-03"])

        # Check aggregated values:
        # 2025-02-01: 1000 (team 12345 only)
        # 2025-02-02: 2000 + 1500 = 3500 (both teams)
        # 2025-02-03: 2500 (team 67890 only)
        expected_data = [1000.0, 3500.0, 2500.0]
        self.assertEqual(events_item.data, expected_data)

    def test_format_history_table_no_team_breakdowns(self):
        """Test when no items have team breakdowns (all global/other items)"""
        usage_history = [
            UsageHistoryItem(
                id=1,
                label="global_events",
                dates=["2025-02-01", "2025-02-02"],
                data=[10000.0, 15000.0],
                breakdown_type=None,
                breakdown_value=["event_count_in_period"],
            ),
            UsageHistoryItem(
                id=2,
                label="global_recordings",
                dates=["2025-02-01", "2025-02-02"],
                data=[500.0, 750.0],
                breakdown_type=None,
                breakdown_value=["recording_count_in_period"],
            ),
        ]

        table = self.tool._format_history_table(usage_history)

        # Should only have aggregated table, no team-specific tables
        self.assertIn("### Overall (all projects)", table)
        self.assertNotIn("### Project", table)  # No project-specific sections

        # Should show aggregated data correctly
        self.assertIn("| Events | 10,000.00 | 15,000.00 |", table)
        self.assertIn("| Recordings | 500.00 | 750.00 |", table)

    def test_format_history_table_spend_vs_usage_items(self):
        """Test that SpendHistoryItem and UsageHistoryItem are handled correctly"""
        usage_history = [
            UsageHistoryItem(
                id=1,
                label="team_events",
                dates=["2025-02-01"],
                data=[1000.0],
                breakdown_type=BillingUsageResponseBreakdownType.MULTIPLE,
                breakdown_value=["event_count_in_period", "123"],
            )
        ]

        spend_history = [
            SpendHistoryItem(
                id=1,
                label="team_spend",
                dates=["2025-02-01"],
                data=[50.0],
                breakdown_type=BillingSpendResponseBreakdownType.MULTIPLE,
                breakdown_value=["event_count_in_period", "123"],
            )
        ]

        self.tool._teams_map = {
            123: "Project 123",
        }

        # Test usage history formatting
        usage_table = self.tool._format_history_table(usage_history)
        self.assertIn("### Overall (all projects)", usage_table)
        self.assertIn("### Project 123", usage_table)
        self.assertIn("| Events | 1,000.00 |", usage_table)

        # Test spend history formatting
        spend_table = self.tool._format_history_table(spend_history)
        self.assertIn("### Overall (all projects)", spend_table)
        self.assertIn("### Project 123", spend_table)
        self.assertIn("| Events | 50.00 |", spend_table)

    def test_format_history_table_edge_case_empty_dates(self):
        """Test handling of items with empty dates or data arrays"""
        usage_history = [
            UsageHistoryItem(
                id=1,
                label="empty_dates",
                dates=[],
                data=[],
                breakdown_type=None,
                breakdown_value=["event_count_in_period"],
            ),
            UsageHistoryItem(
                id=2,
                label="valid_item",
                dates=["2025-02-01"],
                data=[100.0],
                breakdown_type=None,
                breakdown_value=["recording_count_in_period"],
            ),
        ]

        table = self.tool._format_history_table(usage_history)

        # Should handle empty dates gracefully and still show valid data
        self.assertIn("### Overall (all projects)", table)
        self.assertIn("| Recordings | 100.00 |", table)
        # The empty item should be handled without causing errors
