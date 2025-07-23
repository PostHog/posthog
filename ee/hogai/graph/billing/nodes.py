from typing import Any, cast
from uuid import uuid4
from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.billing.prompts import BILLING_CONTEXT_PROMPT
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage, MaxBillingContext, SpendHistoryItem, UsageHistoryItem
from posthog.clickhouse.client import sync_execute

# sync with frontend/src/scenes/billing/constants.ts
USAGE_TYPES = [
    {"label": "Events", "value": "event_count_in_period"},
    {"label": "Recordings", "value": "recording_count_in_period"},
    {"label": "Mobile Recordings", "value": "mobile_recording_count_in_period"},
    {"label": "Feature Flags", "value": "billable_feature_flag_requests_count_in_period"},
    {"label": "Exceptions", "value": "exceptions_captured_in_period"},
    {"label": "Rows Synced", "value": "rows_synced_in_period"},
    {"label": "Persons", "value": "enhanced_persons_event_count_in_period"},
    {"label": "Survey Responses", "value": "survey_responses_count_in_period"},
    {"label": "Data Pipelines", "value": "data_pipelines"},
    {"label": "Group Analytics", "value": "group_analytics"},
]


class BillingNode(AssistantNode):
    _teams_map: dict[int, str] = {}

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        billing_context = self._get_billing_context(config)
        if not billing_context:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="No billing information available", id=str(uuid4()), tool_call_id=str(uuid4())
                    )
                ]
            )
        formatted_billing_context = self._format_billing_context(billing_context)
        tool_call_id = cast(str, state.root_tool_call_id)
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content=formatted_billing_context, tool_call_id=tool_call_id, id=str(uuid4())),
            ]
        )

    def _format_billing_context(self, billing_context: MaxBillingContext) -> str:
        """Format billing context into a readable prompt section."""
        # Convert billing context to a format suitable for the mustache template
        template_data = {
            "subscription_level": billing_context.subscription_level.value
            if billing_context.subscription_level
            else "free",
            "billing_plan": billing_context.billing_plan,
            "has_active_subscription": billing_context.has_active_subscription,
            "is_deactivated": billing_context.is_deactivated,
            "organization_teams_count": len(self._get_teams_map().keys()),
            "current_team_name": self._team.name,
            "current_team_id": self._team.id,
        }

        # Add startup program info
        if billing_context.startup_program_label:
            template_data["startup_program_label"] = billing_context.startup_program_label
        if billing_context.startup_program_label_previous:
            template_data["startup_program_label_previous"] = billing_context.startup_program_label_previous
        if not billing_context.startup_program_label and not billing_context.startup_program_label_previous:
            template_data["startup_program_label"] = "None"

        # Add billing period info
        if billing_context.billing_period:
            template_data["billing_period"] = {
                "current_period_start": billing_context.billing_period.current_period_start,
                "current_period_end": billing_context.billing_period.current_period_end,
                "interval": billing_context.billing_period.interval,
            }

        # Add cost information
        if billing_context.total_current_amount_usd:
            template_data["total_current_amount_usd"] = billing_context.total_current_amount_usd
        if billing_context.projected_total_amount_usd:
            template_data["total_projected_amount_usd"] = billing_context.projected_total_amount_usd
        if billing_context.projected_total_amount_usd_after_discount:
            template_data["total_projected_amount_usd_after_discount"] = (
                billing_context.projected_total_amount_usd_after_discount
            )
        if billing_context.projected_total_amount_usd_with_limit:
            template_data["total_projected_amount_usd_with_limit"] = (
                billing_context.projected_total_amount_usd_with_limit
            )
        if billing_context.projected_total_amount_usd_with_limit_after_discount:
            template_data["total_projected_amount_usd_with_limit_after_discount"] = (
                billing_context.projected_total_amount_usd_with_limit_after_discount
            )

        # Add products information
        if billing_context.products:
            template_data["products"] = []
            for product in billing_context.products:
                product_data = {
                    "name": product.name,
                    "type": product.type,
                    "description": product.description,
                    "current_usage": int(product.current_usage) if product.current_usage else None,
                    "usage_limit": int(product.usage_limit) if product.usage_limit else None,
                    "percentage_usage": product.percentage_usage,
                    "has_exceeded_limit": product.has_exceeded_limit,
                    "custom_limit_usd": product.custom_limit_usd,
                    "next_period_custom_limit_usd": product.next_period_custom_limit_usd,
                    "docs_url": product.docs_url,
                    "projected_amount_usd": product.projected_amount_usd,
                    "projected_amount_usd_with_limit": product.projected_amount_usd_with_limit,
                    "addons": [],
                }
                # Add a flag to check if this product has addons
                if product.addons:
                    product_data["has_addons"] = True
                    product_data["product_name"] = product.name
                for addon in product.addons:
                    addon_data = {
                        "name": addon.name,
                        "type": addon.type,
                        "description": addon.description,
                        "current_usage": int(addon.current_usage) if addon.current_usage else None,
                        "usage_limit": int(addon.usage_limit) if addon.usage_limit else None,
                        "docs_url": addon.docs_url,
                        "projected_amount_usd": addon.projected_amount_usd,
                    }
                    product_data["addons"].append(addon_data)
                template_data["products"].append(product_data)

        # Add trial information
        if billing_context.trial:
            template_data["trial"] = {
                "is_active": billing_context.trial.is_active,
                "expires_at": billing_context.trial.expires_at,
                "target": billing_context.trial.target,
            }

        if billing_context.usage_history:
            # Format usage history as a table with breakdown by date
            usage_table = self._format_history_table(billing_context.usage_history)
            template_data["usage_history_table"] = usage_table

        if billing_context.spend_history:
            # Format spend history as a table with breakdown by date
            spend_table = self._format_history_table(billing_context.spend_history)
            template_data["spend_history_table"] = spend_table

        # Add settings
        template_data["settings"] = {
            "autocapture_on": billing_context.settings.autocapture_on,
            "active_destinations": billing_context.settings.active_destinations,
        }

        # Add top events by usage
        top_events = self._get_top_events_by_usage()
        if top_events:
            template_data["top_events"] = top_events

        template = PromptTemplate.from_template(BILLING_CONTEXT_PROMPT, template_format="mustache")
        return template.format_prompt(**template_data).to_string()

    def _get_teams_map(self) -> dict[int, str]:
        if self._teams_map:
            return self._teams_map
        self._teams_map = {team.id: f"{team.name} (ID: {team.id})" for team in self._team.organization.teams.all()}
        return self._teams_map

    def _format_history_table(self, usage_history: list[UsageHistoryItem] | list[SpendHistoryItem]) -> str:
        """Format multiple breakdowns as breakdown table."""
        if not usage_history:
            return "No data available"

        # Group history items by team if breakdown_value contains team IDs
        tables = []
        team_items: dict[str, list] = {}
        other_items = []

        for item in usage_history:
            # Check if this item has team breakdown
            team_id_found = None
            if item.breakdown_value and isinstance(item.breakdown_value, list):
                # Search for team ID in any position of breakdown_value
                for value in item.breakdown_value:
                    if value in [str(team_id) for team_id in self._get_teams_map().keys()]:
                        team_id_found = value
                        break

            if team_id_found:
                if team_id_found not in team_items:
                    team_items[team_id_found] = []
                team_items[team_id_found].append(item)
            else:
                other_items.append(item)

        # Create tables for each team
        for team_id, items in team_items.items():
            team_name = self._get_teams_map().get(int(team_id), f"Project ID: {team_id}")
            table = self._format_single_team_table(items, team_name)
            tables.append(table)

        # Add table for non-team items if any
        if other_items:
            table = self._format_single_team_table(other_items, "Overall (all projects)")
            tables.append(table)

        return "\n\n".join(tables)

    def _format_single_team_table(self, items: list[UsageHistoryItem] | list[SpendHistoryItem], title: str) -> str:
        """Format a single table for a team or overall data."""
        if not items:
            return f"### {title}\nNo data available"

        # Get all unique dates across all items
        all_dates = set()
        for item in items:
            all_dates.update(item.dates)
        sorted_dates = sorted(all_dates)

        # Build table header
        table_lines = [f"### {title}"]
        if not sorted_dates:
            return f"### {title}\nNo data available"

        # Create header row
        header = "| Data Type | " + " | ".join(sorted_dates) + " |"
        separator = "|" + "|".join([" --- "] * (len(sorted_dates) + 1)) + "|"
        table_lines.extend([header, separator])

        # Add data rows
        for item in items:
            # Create a mapping from date to value
            date_to_value = dict(zip(item.dates, item.data))

            # Build row with values aligned to dates
            row_values = []
            for date in sorted_dates:
                value = date_to_value.get(date, 0)
                # Format the value appropriately
                if isinstance(value, int | float):
                    formatted_value = f"{float(value):,.2f}"
                else:
                    formatted_value = str(value)
                row_values.append(formatted_value)

            label = next((t["label"] for t in USAGE_TYPES if t["value"] == item.label), item.label)
            row = f"| {label} | " + " | ".join(row_values) + " |"
            table_lines.append(row)

        return "\n".join(table_lines)

    def _get_top_events_by_usage(self) -> list[dict[str, Any]]:
        """Get top 20 events by usage over the last 30 days for the current team."""
        try:
            query = """
                SELECT
                    event,
                    count() as count
                FROM events
                WHERE
                    team_id = %(team_id)s
                    AND timestamp >= now() - INTERVAL 30 DAY
                GROUP BY
                    event
                ORDER BY
                    count DESC
                LIMIT 20
            """

            results = sync_execute(query, {"team_id": self._team.id})
            if isinstance(results, list):
                return [
                    {"event": row[0], "count": int(row[1]), "formatted_count": f"{int(row[1]):,}"} for row in results
                ]
            return []
        except Exception:
            # If query fails, return empty list
            return []
