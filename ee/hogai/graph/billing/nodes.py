from typing import Any, cast
from uuid import uuid4
from datetime import datetime, timedelta
from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.billing.prompts import BILLING_CONTEXT_PROMPT
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage, MaxBillingContext
from posthog.clickhouse.client import sync_execute


class BillingNode(AssistantNode):
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
        }

        # Add startup program info
        if billing_context.startup_program_label:
            template_data["startup_program_label"] = billing_context.startup_program_label

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
        if billing_context.total_projected_amount_usd:
            template_data["total_projected_amount_usd"] = billing_context.total_projected_amount_usd

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
                }
                template_data["products"].append(product_data)

        # Add addons information
        if billing_context.addons:
            template_data["addons"] = []
            for addon in billing_context.addons:
                addon_data = {
                    "name": addon.name,
                    "type": addon.type,
                    "description": addon.description,
                    "current_usage": int(addon.current_usage) if addon.current_usage else None,
                    "usage_limit": int(addon.usage_limit) if addon.usage_limit else None,
                    "docs_url": addon.docs_url,
                }
                template_data["addons"].append(addon_data)

        # Add trial information
        if billing_context.trial:
            template_data["trial"] = {
                "is_active": billing_context.trial.is_active,
                "expires_at": billing_context.trial.expires_at,
                "target": billing_context.trial.target,
            }

        if billing_context.usage_history:
            # Format usage history as a table with breakdown by date
            usage_table = self._format_usage_history_table(billing_context.usage_history)
            template_data["usage_history_table"] = usage_table

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

    def _format_usage_history_table(self, usage_history) -> str:
        """Format multiple breakdowns as compact weekly breakdown table."""

        # Create dynamic header with breakdown columns
        breakdown_names = [result.breakdown_value or "Unknown" for result in usage_history]
        header = "| Week | " + " | ".join(breakdown_names) + " |"
        separator = "|------|" + "|".join(["-------"] * len(breakdown_names)) + "|"

        table_lines = [header, separator]

        # Get all unique weeks across all breakdowns
        all_weeks: set[str] = set()
        breakdown_data: dict[int, dict[str, float]] = {}
        week_date_mapping: dict[str, str] = {}  # Maps week_key to actual date range

        for i, result in enumerate(usage_history):
            breakdown_data[i] = {}
            if result.dates and result.data:
                for date, usage in zip(result.dates, result.data):
                    try:
                        date_obj = datetime.strptime(date, "%Y-%m-%d")
                        # Calculate the start of the week (Monday)
                        days_since_monday = date_obj.weekday()
                        week_start = date_obj - timedelta(days=days_since_monday)
                        week_end = week_start + timedelta(days=6)
                        week_key = week_start.strftime("%Y-%m-%d")  # Use start date as key
                        week_range = f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}"

                        all_weeks.add(week_key)
                        week_date_mapping[week_key] = week_range
                        breakdown_data[i][week_key] = float(usage) if usage is not None else 0
                    except (ValueError, TypeError):
                        # Fallback to original date format if parsing fails
                        week_key = date
                        all_weeks.add(week_key)
                        week_date_mapping[week_key] = date
                        breakdown_data[i][week_key] = float(usage) if usage is not None else 0

        # Sort weeks and show most recent 4-6 weeks
        sorted_weeks = sorted(all_weeks)[-6:] if len(all_weeks) > 6 else sorted(all_weeks)

        # Create rows for each week
        for week in sorted_weeks:
            week_totals = []
            for i in range(len(usage_history)):
                total = breakdown_data[i].get(week, 0)
                if total >= 1000:
                    week_totals.append(f"{total:,.0f}")
                else:
                    week_totals.append(f"{total:.0f}")

            week_display = week_date_mapping.get(week, week)
            week_row = f"| {week_display} | " + " | ".join(week_totals) + " |"
            table_lines.append(week_row)

        return "\n".join(table_lines)

    def _get_top_events_by_usage(self) -> list[dict[str, Any]]:
        """Get top 20 events by usage over the last 30 days."""
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
