from textwrap import dedent
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.schema import (
    AlertCalculationInterval,
    AlertConditionType,
    InsightThresholdType,
    InsightVizNode,
    QuerySchemaRoot,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.alert import AlertConfiguration, AlertSubscription, Threshold, are_alerts_supported_for_insight
from posthog.models.insight import Insight

from ee.hogai.artifacts.types import ModelArtifactResult
from ee.hogai.tool import MaxTool

ALERT_CREATION_TOOL_DESCRIPTION = dedent("""
    Use this tool to create alerts that monitor insight metrics and notify users when conditions are met.

    # When to use
    - User wants to be notified when a metric crosses a threshold
    - User wants to monitor an insight for anomalies or changes
    - User mentions alerts, notifications, or monitoring for insights

    # Requirements
    - Only works for TrendsQuery insights (not funnels, retention, etc.)
    - An insight must be available via insight_id or from the current context

    # Identifying the insight
    - **insight_id**: The ID of the insight to monitor. This can be a numeric database ID or a string short ID (e.g., "M3dD2XyC" from a visualization you just created with create_insight). If the visualization is not yet saved, it will be saved automatically as a new insight.
    - If not provided, the tool falls back to the insight from the current page context.

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
    - "Create a trend for signups and alert me if it drops": First use create_insight, then use create_alert with the insight_id from the visualization

    # Listing alerts
    - To list existing alerts, use the list_data tool with kind="alerts"
    - To view alerts in the UI, direct the user to /insights?tab=alerts
    - To view alerts for a specific insight, direct the user to /insights/{insightShortId}/alerts
    """).strip()


class CreateAlertToolArgs(BaseModel):
    name: str = Field(description="Alert name (e.g., 'Daily signups below 100')")
    condition_type: AlertConditionType = Field(
        description="Type of condition: absolute_value, relative_increase, or relative_decrease"
    )
    insight_id: str | None = Field(
        default=None,
        description="ID of the insight to monitor. Accepts a numeric database ID or a string short ID (e.g., from a visualization created with create_insight). If not provided, uses the insight from the current context.",
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

    async def _check_alert_limit(self) -> str | None:
        team = self._team
        org = await sync_to_async(lambda: team.organization)()
        return await sync_to_async(AlertConfiguration.check_alert_limit)(team.id, org)

    @staticmethod
    def _is_numeric_id(value: str) -> bool:
        try:
            int(float(value))
            return True
        except (ValueError, TypeError):
            return False

    async def _resolve_insight_by_numeric_id(self, numeric_id: int) -> Insight:
        """Look up an insight by its numeric database ID."""
        return await sync_to_async(Insight.objects.get)(id=numeric_id, team=self._team)

    async def _resolve_insight_from_artifact(self, artifact_id: str) -> tuple[Insight, bool]:
        """Resolve a visualization artifact or short_id to a persisted Insight.

        Checks sources in priority order: conversation state, artifact DB, insights table.
        If the artifact is transient, creates and saves a new Insight.

        Returns (insight, was_created) — was_created is True when a new Insight was persisted.
        """
        result = await self._context_manager.artifacts.aget_visualization(self._state.messages, artifact_id)

        if result is None:
            raise ValueError(f"Insight or visualization '{artifact_id}' not found.")

        if isinstance(result, ModelArtifactResult):
            return result.model, False

        # Transient artifact (State or DB artifact) — persist as a saved Insight
        content = result.content
        coerced_query = QuerySchemaRoot.model_validate(content.query.model_dump(mode="json")).root
        converted = InsightVizNode(source=coerced_query).model_dump(exclude_none=True)

        insight = await sync_to_async(Insight.objects.create)(
            team=self._team,
            created_by=self._user,
            name=(content.name or "Untitled")[:400],
            description=(content.description or "")[:400],
            query=converted,
            saved=True,
        )
        return insight, True

    async def _resolve_insight(self, insight_id: str | None) -> tuple[Insight, bool]:
        """Resolve an insight from any ID format or context.

        Tries in order:
        1. Numeric DB ID lookup
        2. Artifact/short_id resolution (conversation state → artifact DB → insights table)
        3. Context insight_id fallback

        Returns (insight, was_created).
        """
        effective_id = insight_id or str(self.context.get("insight_id") or "")
        if not effective_id:
            raise ValueError("No insight provided. Provide an insight_id or navigate to an insight first.")

        # Try numeric DB ID first
        if self._is_numeric_id(effective_id):
            try:
                insight = await self._resolve_insight_by_numeric_id(int(float(effective_id)))
                return insight, False
            except Insight.DoesNotExist:
                pass  # Fall through to artifact resolution

        # Try artifact/short_id resolution
        return await self._resolve_insight_from_artifact(effective_id)

    @staticmethod
    @sync_to_async
    @transaction.atomic
    def _persist_alert(
        *, team, user, insight, name, unsaved_threshold, condition, config, calculation_interval, enabled, skip_weekend
    ):
        unsaved_threshold.save()

        alert = AlertConfiguration.objects.create(
            team=team,
            insight=insight,
            name=name,
            threshold=unsaved_threshold,
            condition=condition,
            config=config,
            calculation_interval=calculation_interval,
            enabled=enabled,
            skip_weekend=skip_weekend,
            created_by=user,
        )

        AlertSubscription.objects.create(
            user=user,
            alert_configuration=alert,
            created_by=user,
        )

        return alert, unsaved_threshold

    async def _arun_impl(
        self,
        name: str,
        condition_type: AlertConditionType,
        insight_id: str | None = None,
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

            if upper_threshold is None and lower_threshold is None:
                return "At least one threshold (upper or lower) must be provided.", {
                    "error": "validation_failed",
                }

            limit_error = await self._check_alert_limit()
            if limit_error:
                return limit_error, {"error": "plan_limit_reached"}

            try:
                insight, saved_new_insight = await self._resolve_insight(insight_id)
            except ValueError as e:
                return str(e), {"error": "insight_resolution_failed"}

            if insight.team_id != team.id:
                return "Insight not found.", {"error": "insight_resolution_failed"}

            await self.check_object_access(insight, "editor", resource="insight", action="create alert for")

            is_supported = await sync_to_async(are_alerts_supported_for_insight)(insight)
            if not is_supported:
                return "Alerts are only supported for TrendsQuery insights. This insight type is not supported.", {
                    "error": "unsupported_insight",
                }

            threshold_config = {
                "type": threshold_type,
                "bounds": {},
            }
            if lower_threshold is not None:
                threshold_config["bounds"]["lower"] = lower_threshold
            if upper_threshold is not None:
                threshold_config["bounds"]["upper"] = upper_threshold

            truncated_name = name[:255]

            unsaved_threshold = Threshold(
                team=team, insight=insight, name=truncated_name, configuration=threshold_config, created_by=user
            )
            try:
                unsaved_threshold.clean()
            except ValidationError as e:
                return str(e), {"error": "validation_failed"}

            alert, threshold = await self._persist_alert(
                team=team,
                user=user,
                insight=insight,
                name=truncated_name,
                unsaved_threshold=unsaved_threshold,
                condition={"type": condition_type},
                config={"type": "TrendsAlertConfig", "series_index": series_index},
                calculation_interval=calculation_interval,
                enabled=enabled,
                skip_weekend=skip_weekend,
            )

            status = "enabled" if enabled else "disabled (draft)"
            alert_url = f"/insights/{insight.short_id}/alerts?alert_id={alert.id}"
            message = (
                f"Alert '{name}' created successfully and is {status}."
                f" [View alert]({alert_url})."
                f" You will be notified when conditions are met."
            )
            if saved_new_insight:
                message += f" The visualization was saved as insight '{insight.name or insight.short_id}'."

            return (
                message,
                {
                    "alert_id": str(alert.id),
                    "alert_name": name,
                    "alert_url": alert_url,
                    "insight_id": insight.id,
                    "insight_short_id": insight.short_id,
                },
            )

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create alert: {str(e)}", {"error": "creation_failed", "details": str(e)}
