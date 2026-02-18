from textwrap import dedent
from typing import Any, Literal, Union

from django.core.exceptions import ValidationError
from django.db import transaction

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.schema import (
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
    InsightVizNode,
    QuerySchemaRoot,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.alert import AlertConfiguration, AlertSubscription, Threshold, are_alerts_supported_for_insight
from posthog.models.insight import Insight

from ee.hogai.artifacts.types import ModelArtifactResult
from ee.hogai.tool import MaxTool

UPSERT_ALERT_TOOL_DESCRIPTION = dedent("""
    Use this tool to create or edit alerts that monitor insight metrics and notify users when conditions are met.

    # When to use
    - User wants to be notified when a metric crosses a threshold
    - User wants to monitor an insight for anomalies or changes
    - User mentions alerts, notifications, or monitoring for insights
    - User wants to change an existing alert's threshold, condition, name, or interval
    - User wants to enable or disable an alert

    # Actions
    - **create**: Create a new alert (requires name and condition_type)
    - **update**: Edit an existing alert (requires alert_id, all other fields are optional)

    # Requirements
    - Only works for TrendsQuery insights (not funnels, retention, etc.)
    - For create: an insight must be available via insight_id or from the current context
    - For update: the alert_id must be provided (find it via list_data with kind="alerts")

    # Identifying the insight (create only)
    - **insight_id**: The ID of the insight to monitor. This can be a numeric database ID, a string short ID, or the ID of a visualization you just created with create_insight. If the visualization is not yet saved, it will be saved automatically as a new insight.
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
    - **daily**: Check once per day (default for create)
    - **weekly**: Check once per week
    - **monthly**: Check once per month

    # Series index
    - If the insight has multiple series (e.g., multiple event types), use series_index to specify which one to monitor
    - Default is 0 (first series) for create

    # Create examples
    - "Alert me when daily signups drop below 100": action=create, condition_type=absolute_value, lower_threshold=100
    - "Alert when pageviews increase by more than 50%": action=create, condition_type=relative_increase, upper_threshold=0.5, threshold_type=percentage
    - "Notify me if revenue drops more than 20% week over week": action=create, condition_type=relative_decrease, lower_threshold=0.2, threshold_type=percentage, calculation_interval=weekly

    # Update examples
    - "Change my alert threshold to 200": action=update, alert_id=<id>, upper_threshold=200
    - "Disable the signups alert": action=update, alert_id=<id>, enabled=false
    - "Change the alert to check weekly": action=update, alert_id=<id>, calculation_interval=weekly
    - "Rename my alert to 'Revenue drop'": action=update, alert_id=<id>, name="Revenue drop"

    # Listing alerts
    - To list existing alerts, use the list_data tool with kind="alerts"
    - To view alerts in the UI, direct the user to /insights?tab=alerts
    - To view alerts for a specific insight, direct the user to /insights/{insightShortId}/alerts
    """).strip()


class CreateAlertAction(BaseModel):
    action: Literal["create"] = "create"
    name: str = Field(description="Alert name (e.g., 'Daily signups below 100')")
    condition_type: AlertConditionType = Field(
        description="Type of condition: absolute_value, relative_increase, or relative_decrease"
    )
    insight_id: str | int | None = Field(
        default=None,
        description="ID of the insight to monitor. Accepts a numeric database ID, a string short ID, or a visualization artifact ID from create_insight. If not provided, uses the insight from the current context.",
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


class UpdateAlertAction(BaseModel):
    action: Literal["update"] = "update"
    alert_id: str = Field(description="The ID of the alert to update (find via list_data with kind='alerts')")
    name: str | None = Field(default=None, description="New alert name")
    condition_type: AlertConditionType | None = Field(default=None, description="New condition type")
    insight_id: str | int | None = Field(
        default=None,
        description="Move the alert to a different insight by providing its ID",
    )
    calculation_interval: AlertCalculationInterval | None = Field(default=None, description="New calculation interval")
    upper_threshold: float | None = Field(default=None, description="New upper threshold bound")
    lower_threshold: float | None = Field(default=None, description="New lower threshold bound")
    threshold_type: InsightThresholdType | None = Field(default=None, description="New threshold type")
    series_index: int | None = Field(default=None, description="New series index to monitor")
    enabled: bool | None = Field(default=None, description="Enable or disable the alert")
    skip_weekend: bool | None = Field(default=None, description="Whether to skip weekend checks")


UpsertAlertAction = Union[CreateAlertAction, UpdateAlertAction]


class UpsertAlertToolArgs(BaseModel):
    action: UpsertAlertAction = Field(
        description="The action to perform. Either create a new alert or update an existing one.",
        discriminator="action",
    )


class UpsertAlertTool(MaxTool):
    name: str = "upsert_alert"
    description: str = UPSERT_ALERT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = UpsertAlertToolArgs

    def get_required_resource_access(self):
        return [("alert", "editor")]

    async def _arun_impl(self, action: UpsertAlertAction) -> tuple[str, dict[str, Any]]:
        if isinstance(action, CreateAlertAction):
            return await self._handle_create(action)
        else:
            return await self._handle_update(action)

    # -- Create --

    async def _handle_create(self, action: CreateAlertAction) -> tuple[str, dict[str, Any]]:
        try:
            team = self._team
            user = self._user

            if action.upper_threshold is None and action.lower_threshold is None:
                return "At least one threshold (upper or lower) must be provided.", {
                    "error": "validation_failed",
                }

            limit_error = await self._check_alert_limit()
            if limit_error:
                return limit_error, {"error": "plan_limit_reached"}

            try:
                insight, was_auto_saved = await self._resolve_insight(action.insight_id)
            except Insight.DoesNotExist:
                return "Insight not found. Provide a valid insight ID or short ID.", {
                    "error": "insight_not_found",
                }

            await self.check_object_access(insight, "editor", resource="insight", action="create alert for")

            is_supported = await sync_to_async(are_alerts_supported_for_insight)(insight)
            if not is_supported:
                return "Alerts are only supported for TrendsQuery insights. This insight type is not supported.", {
                    "error": "unsupported_insight",
                }

            threshold_config = {
                "type": action.threshold_type,
                "bounds": {},
            }
            if action.lower_threshold is not None:
                threshold_config["bounds"]["lower"] = action.lower_threshold
            if action.upper_threshold is not None:
                threshold_config["bounds"]["upper"] = action.upper_threshold

            truncated_name = action.name[:255]

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
                condition={"type": action.condition_type},
                config={"type": "TrendsAlertConfig", "series_index": action.series_index},
                calculation_interval=action.calculation_interval,
                enabled=action.enabled,
                skip_weekend=action.skip_weekend,
            )

            status = "enabled" if action.enabled else "disabled (draft)"
            alert_url = f"/insights/{insight.short_id}/alerts?alert_id={alert.id}"
            message = f"Alert '{action.name}' created successfully and is {status}. [View alert]({alert_url})."
            if was_auto_saved:
                message += (
                    f" The visualization was automatically saved as insight"
                    f" '{insight.name or insight.short_id}' so the alert can monitor it."
                )

            return (
                message,
                {
                    "alert_id": str(alert.id),
                    "alert_name": action.name,
                    "alert_url": alert_url,
                    "insight_id": insight.id,
                    "insight_short_id": insight.short_id,
                    "insight_auto_saved": was_auto_saved,
                },
            )

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create alert: {str(e)}", {"error": "creation_failed", "details": str(e)}

    # -- Update --

    async def _handle_update(self, action: UpdateAlertAction) -> tuple[str, dict[str, Any]]:
        try:
            alert = await self._resolve_alert(action.alert_id)
            if alert is None:
                return f"Alert '{action.alert_id}' not found.", {"error": "alert_not_found"}

            await self.check_object_access(alert, "editor", resource="alert", action="edit")

            conditions_or_threshold_changed = False
            calculation_interval_changed = False
            update_fields: list[str] = []

            if action.name is not None:
                alert.name = action.name[:255]
                update_fields.append("name")

            if action.condition_type is not None:
                alert.condition = {"type": action.condition_type}
                update_fields.append("condition")
                conditions_or_threshold_changed = True

            if action.calculation_interval is not None and action.calculation_interval != alert.calculation_interval:
                alert.calculation_interval = action.calculation_interval
                update_fields.append("calculation_interval")
                calculation_interval_changed = True

            if action.series_index is not None:
                alert.config = {**(alert.config or {}), "series_index": action.series_index}
                update_fields.append("config")

            if action.enabled is not None:
                alert.enabled = action.enabled
                update_fields.append("enabled")

            if action.skip_weekend is not None:
                alert.skip_weekend = action.skip_weekend
                update_fields.append("skip_weekend")

            if action.insight_id is not None:
                try:
                    insight, _ = await self._resolve_insight(action.insight_id)
                except Insight.DoesNotExist:
                    return "Insight not found. Provide a valid insight ID or short ID.", {
                        "error": "insight_not_found",
                    }
                is_supported = await sync_to_async(are_alerts_supported_for_insight)(insight)
                if not is_supported:
                    return "Alerts are only supported for TrendsQuery insights. This insight type is not supported.", {
                        "error": "unsupported_insight",
                    }
                alert.insight = insight
                update_fields.append("insight")

            has_threshold_changes = (
                action.upper_threshold is not None
                or action.lower_threshold is not None
                or action.threshold_type is not None
            )
            if has_threshold_changes:
                await self._update_threshold(alert, action)
                conditions_or_threshold_changed = True

            if not update_fields and not has_threshold_changes:
                return "No changes provided. Specify at least one field to update.", {"error": "no_changes"}

            if conditions_or_threshold_changed:
                alert.state = AlertState.NOT_FIRING
                update_fields.append("state")

            if conditions_or_threshold_changed or calculation_interval_changed:
                alert.next_check_at = None
                update_fields.append("next_check_at")

            await sync_to_async(alert.save)(update_fields=update_fields)

            insight = await sync_to_async(lambda: alert.insight)()
            alert_url = f"/insights/{insight.short_id}/alerts?alert_id={alert.id}"
            return (
                f"Alert '{alert.name}' updated successfully. [View alert]({alert_url}).",
                {
                    "alert_id": str(alert.id),
                    "alert_name": alert.name,
                    "alert_url": alert_url,
                },
            )

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to update alert: {str(e)}", {"error": "update_failed", "details": str(e)}

    async def _resolve_alert(self, alert_id: str) -> AlertConfiguration | None:
        alert_id = str(alert_id).strip()
        if not alert_id:
            return None
        try:
            return await AlertConfiguration.objects.select_related("threshold", "insight").aget(
                id=alert_id, team=self._team
            )
        except (AlertConfiguration.DoesNotExist, ValueError, ValidationError):
            return None

    @staticmethod
    async def _update_threshold(alert: AlertConfiguration, action: UpdateAlertAction) -> None:
        threshold = alert.threshold
        if threshold is None:
            config: dict[str, Any] = {
                "type": action.threshold_type or InsightThresholdType.ABSOLUTE,
                "bounds": {},
            }
            if action.lower_threshold is not None:
                config["bounds"]["lower"] = action.lower_threshold
            if action.upper_threshold is not None:
                config["bounds"]["upper"] = action.upper_threshold

            insight = await sync_to_async(lambda: alert.insight)()
            team = await sync_to_async(lambda: alert.team)()
            threshold = await sync_to_async(Threshold.objects.create)(
                team=team, insight=insight, name=alert.name, configuration=config
            )
            alert.threshold = threshold
            return

        config = dict(threshold.configuration)
        if action.threshold_type is not None:
            config["type"] = action.threshold_type
        bounds = dict(config.get("bounds", {}))
        if action.lower_threshold is not None:
            bounds["lower"] = action.lower_threshold
        if action.upper_threshold is not None:
            bounds["upper"] = action.upper_threshold
        config["bounds"] = bounds
        threshold.configuration = config
        await sync_to_async(threshold.save)(update_fields=["configuration"])

    # -- Shared helpers --

    async def _check_alert_limit(self) -> str | None:
        team = self._team
        org = await sync_to_async(lambda: team.organization)()
        return await sync_to_async(AlertConfiguration.check_alert_limit)(team.id, org)

    async def _resolve_insight(self, insight_id: str | int | None) -> tuple[Insight, bool]:
        """Resolve an insight by numeric ID, short_id, or conversation artifact.

        Tries in order:
        1. Numeric database ID
        2. Short ID (saved insight)
        3. Conversation artifact (transient visualization — auto-saved as a new insight)

        Returns (insight, was_auto_saved).
        """
        effective_id = str(insight_id or self.context.get("insight_id") or "").strip()
        if not effective_id:
            raise Insight.DoesNotExist(
                "No insight provided. Provide an insight_id or use this tool from an insight page."
            )

        qs = Insight.objects.filter(team=self._team, deleted=False)

        # 1. Try numeric DB ID
        try:
            return await sync_to_async(qs.get)(id=int(effective_id)), False
        except (ValueError, Insight.DoesNotExist):
            pass

        # 2. Try short_id
        try:
            return await sync_to_async(qs.get)(short_id=effective_id), False
        except Insight.DoesNotExist:
            pass

        # 3. Try conversation artifact — auto-save as a new insight (same pattern as upsert_dashboard)
        result = await self._context_manager.artifacts.aget_visualization(self._state.messages, effective_id)
        if result is None:
            raise Insight.DoesNotExist(f"Insight or visualization '{effective_id}' not found.")

        if isinstance(result, ModelArtifactResult):
            return result.model, False

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
