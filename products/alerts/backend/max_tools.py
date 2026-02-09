from textwrap import dedent
from typing import Any

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.schema import AlertCalculationInterval, AlertConditionType, InsightThresholdType

from posthog.exceptions_capture import capture_exception
from posthog.models.alert import AlertConfiguration, AlertSubscription, Threshold, are_alerts_supported_for_insight
from posthog.models.insight import Insight

from ee.hogai.tool import MaxTool

ALERT_CREATION_TOOL_DESCRIPTION = dedent("""
    Use this tool to create alerts that monitor insight metrics and notify users when conditions are met.

    # When to use
    - User wants to be notified when a metric crosses a threshold
    - User wants to monitor an insight for anomalies or changes
    - User mentions alerts, notifications, or monitoring for insights

    # Requirements
    - Only works for TrendsQuery insights (not funnels, retention, etc.)
    - An insight must be available either from the current context or via insight_id

    # Condition types
    - **absolute_value**: Fires when the metric's absolute value crosses the threshold bounds
    - **relative_increase**: Fires when the metric increases by more than the threshold (use upper_threshold)
    - **relative_decrease**: Fires when the metric decreases by more than the threshold (use lower_threshold)

    # Threshold configuration
    - **lower_threshold**: Lower bound - alert fires when value drops below this
    - **upper_threshold**: Upper bound - alert fires when value exceeds this
    - You can set one or both bounds
    - For percentage-based thresholds, set threshold_type to "percentage" and use decimal values (e.g., 0.5 for 50%)

    # Calculation intervals
    - **hourly**: Check every hour
    - **daily**: Check once per day (default)
    - **weekly**: Check once per week
    - **monthly**: Check once per month

    # Series index
    - If the insight has multiple series (e.g., multiple event types), use series_index to specify which one to monitor
    - Default is 0 (first series)

    # Examples
    - "Alert me when daily signups drop below 100": condition_type=absolute_value, lower_threshold=100
    - "Alert when pageviews increase by more than 50%": condition_type=relative_increase, upper_threshold=0.5, threshold_type=percentage
    - "Notify me if revenue drops more than 20% week over week": condition_type=relative_decrease, lower_threshold=0.2, threshold_type=percentage, calculation_interval=weekly
    """).strip()


class CreateAlertToolArgs(BaseModel):
    name: str = Field(description="Alert name (e.g., 'Daily signups below 100')")
    condition_type: AlertConditionType = Field(
        description="Type of condition: absolute_value, relative_increase, or relative_decrease"
    )
    insight_id: int | None = Field(
        default=None,
        description="ID of the insight to monitor. If not provided, uses the insight from the current context.",
    )
    calculation_interval: AlertCalculationInterval = Field(
        default=AlertCalculationInterval.DAILY,
        description="How often to check: hourly, daily, weekly, or monthly",
    )
    upper_threshold: float | None = Field(
        default=None,
        description="Upper bound - alert fires when value exceeds this",
    )
    lower_threshold: float | None = Field(
        default=None,
        description="Lower bound - alert fires when value drops below this",
    )
    threshold_type: InsightThresholdType = Field(
        default=InsightThresholdType.ABSOLUTE,
        description="Whether thresholds are absolute values or percentages (use decimal, e.g. 0.5 for 50%)",
    )
    series_index: int = Field(
        default=0,
        description="Which series to monitor (0-indexed). Use 0 for single-series insights.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the alert should be enabled immediately",
    )
    skip_weekend: bool = Field(
        default=False,
        description="Whether to skip weekend checks",
    )


class CreateAlertTool(MaxTool):
    name: str = "create_alert"
    description: str = ALERT_CREATION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateAlertToolArgs

    def get_required_resource_access(self):
        return [("alert", "editor")]

    async def is_dangerous_operation(self, **kwargs) -> bool:
        return kwargs.get("enabled", True) is True

    async def format_dangerous_operation_preview(self, **kwargs) -> str:
        name = kwargs.get("name", "Untitled Alert")
        condition_type = kwargs.get("condition_type", "absolute_value")
        interval = kwargs.get("calculation_interval", AlertCalculationInterval.DAILY)
        lower = kwargs.get("lower_threshold")
        upper = kwargs.get("upper_threshold")
        threshold_type = kwargs.get("threshold_type", InsightThresholdType.ABSOLUTE)

        is_pct = threshold_type == InsightThresholdType.PERCENTAGE

        parts = [f"**Create and enable** alert '{name}'"]

        condition_desc = {
            AlertConditionType.ABSOLUTE_VALUE: "absolute value",
            AlertConditionType.RELATIVE_INCREASE: "relative increase",
            AlertConditionType.RELATIVE_DECREASE: "relative decrease",
        }.get(condition_type, str(condition_type))
        parts.append(f"Condition: {condition_desc}")

        bounds = []
        if lower is not None:
            bounds.append(f"lower: {lower * 100 if is_pct else lower}{'%' if is_pct else ''}")
        if upper is not None:
            bounds.append(f"upper: {upper * 100 if is_pct else upper}{'%' if is_pct else ''}")
        if bounds:
            parts.append(f"Thresholds: {', '.join(bounds)}")

        parts.append(f"Check interval: {interval}")
        parts.append("It will immediately start monitoring and sending notifications.")

        return "\n".join(parts)

    async def _arun_impl(
        self,
        name: str,
        condition_type: AlertConditionType,
        insight_id: int | None = None,
        calculation_interval: AlertCalculationInterval = AlertCalculationInterval.DAILY,
        upper_threshold: float | None = None,
        lower_threshold: float | None = None,
        threshold_type: InsightThresholdType = InsightThresholdType.ABSOLUTE,
        series_index: int = 0,
        enabled: bool = True,
        skip_weekend: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        try:
            team = self._team
            user = self._user

            effective_insight_id = insight_id or self.context.get("insight_id")
            if not effective_insight_id:
                return "No insight ID provided. Please provide an insight_id or navigate to an insight first.", {
                    "error": "no_insight_id",
                }

            try:
                insight = await sync_to_async(Insight.objects.get)(id=effective_insight_id, team=team)
            except Insight.DoesNotExist:
                return f"Insight with ID {effective_insight_id} not found.", {
                    "error": "not_found",
                }

            await self.check_object_access(insight, "editor", resource="insight", action="create alert for")

            is_supported = await sync_to_async(are_alerts_supported_for_insight)(insight)
            if not is_supported:
                return "Alerts are only supported for TrendsQuery insights. This insight type is not supported.", {
                    "error": "unsupported_insight",
                }

            if upper_threshold is None and lower_threshold is None:
                return "At least one threshold (upper or lower) must be provided.", {
                    "error": "validation_failed",
                }

            threshold_config = {
                "type": threshold_type,
                "bounds": {},
            }
            if lower_threshold is not None:
                threshold_config["bounds"]["lower"] = lower_threshold
            if upper_threshold is not None:
                threshold_config["bounds"]["upper"] = upper_threshold

            threshold = await sync_to_async(Threshold.objects.create)(
                team=team,
                insight=insight,
                name=name,
                configuration=threshold_config,
                created_by=user,
            )

            alert_condition = {"type": condition_type}
            alert_config = {
                "type": "TrendsAlertConfig",
                "series_index": series_index,
            }

            alert = await sync_to_async(AlertConfiguration.objects.create)(
                team=team,
                insight=insight,
                name=name,
                threshold=threshold,
                condition=alert_condition,
                config=alert_config,
                calculation_interval=calculation_interval,
                enabled=enabled,
                skip_weekend=skip_weekend,
                created_by=user,
            )

            await sync_to_async(AlertSubscription.objects.create)(
                user=user,
                alert_configuration=alert,
                created_by=user,
            )

            status = "enabled" if enabled else "disabled (draft)"
            return (
                f"Alert '{name}' created successfully and is {status}. You will be notified when conditions are met.",
                {
                    "alert_id": str(alert.id),
                    "alert_name": name,
                    "insight_id": insight.id,
                },
            )

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create alert: {str(e)}", {"error": "creation_failed", "details": str(e)}
