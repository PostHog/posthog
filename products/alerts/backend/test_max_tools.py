import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import AlertCalculationInterval, AlertConditionType, AlertState, InsightThresholdType

from posthog.models import Organization, Team
from posthog.models.alert import AlertConfiguration, AlertSubscription, Threshold
from posthog.models.insight import Insight

from .max_tools import CreateAlertAction, UpdateAlertAction, UpsertAlertTool


class TestUpsertAlertTool(BaseTest):
    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def _setup_tool(self, context: dict | None = None):
        config = self._config
        if context:
            config = {
                **self._config,
                "configurable": {
                    **self._config.get("configurable", {}),
                    "contextual_tools": {"upsert_alert": context},
                },
            }
        return UpsertAlertTool(team=self.team, user=self.user, config=config)

    async def _create_trends_insight(self, name: str = "Test Insight", team: Team | None = None) -> Insight:
        return await sync_to_async(Insight.objects.create)(
            team=team or self.team,
            name=name,
            created_by=self.user,
            query={
                "kind": "InsightVizNode",
                "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )

    async def _create_funnel_insight(self) -> Insight:
        return await sync_to_async(Insight.objects.create)(
            team=self.team,
            name="Test Funnel",
            created_by=self.user,
            query={
                "kind": "InsightVizNode",
                "source": {"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )

    async def _create_alert(
        self,
        insight: Insight,
        name: str = "Test Alert",
        condition_type: AlertConditionType = AlertConditionType.ABSOLUTE_VALUE,
        lower_threshold: float | None = 100.0,
        upper_threshold: float | None = None,
        threshold_type: InsightThresholdType = InsightThresholdType.ABSOLUTE,
        calculation_interval: AlertCalculationInterval = AlertCalculationInterval.DAILY,
        enabled: bool = True,
    ) -> AlertConfiguration:
        threshold_config: dict = {"type": threshold_type, "bounds": {}}
        if lower_threshold is not None:
            threshold_config["bounds"]["lower"] = lower_threshold
        if upper_threshold is not None:
            threshold_config["bounds"]["upper"] = upper_threshold

        def _create():
            threshold = Threshold.objects.create(
                team=self.team,
                insight=insight,
                name=name,
                configuration=threshold_config,
                created_by=self.user,
            )
            alert = AlertConfiguration.objects.create(
                team=self.team,
                insight=insight,
                name=name,
                threshold=threshold,
                condition={"type": condition_type},
                config={"type": "TrendsAlertConfig", "series_index": 0},
                calculation_interval=calculation_interval,
                enabled=enabled,
                created_by=self.user,
            )
            AlertSubscription.objects.create(
                user=self.user,
                alert_configuration=alert,
                created_by=self.user,
            )
            return alert

        return await sync_to_async(_create)()

    # -- Create: happy path --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_success(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Daily signups below 100",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        assert artifact["alert_name"] == "Daily signups below 100"
        assert artifact["insight_id"] == insight.id
        assert artifact["insight_auto_saved"] is False

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.name == "Daily signups below 100"
        assert alert.enabled is True
        assert alert.calculation_interval == AlertCalculationInterval.DAILY

        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["bounds"]["lower"] == 100.0
        assert threshold.configuration["type"] == InsightThresholdType.ABSOLUTE

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_with_both_bounds(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Value in range",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=50.0,
                upper_threshold=200.0,
            )
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["bounds"]["lower"] == 50.0
        assert threshold.configuration["bounds"]["upper"] == 200.0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_percentage_threshold(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="50% increase alert",
                condition_type=AlertConditionType.RELATIVE_INCREASE,
                insight_id=insight.id,
                upper_threshold=0.5,
                threshold_type=InsightThresholdType.PERCENTAGE,
            )
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["type"] == InsightThresholdType.PERCENTAGE
        assert threshold.configuration["bounds"]["upper"] == 0.5

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_from_context(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool(context={"insight_id": insight.id})

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Context-based alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                lower_threshold=50.0,
            )
        )

        assert "created successfully" in content
        assert artifact["insight_id"] == insight.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_subscribes_current_user(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Subscription test",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        subscription = await sync_to_async(AlertSubscription.objects.get)(alert_configuration=alert)
        assert subscription.user_id == self.user.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_with_custom_interval(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Weekly alert",
                condition_type=AlertConditionType.RELATIVE_DECREASE,
                insight_id=insight.id,
                lower_threshold=0.2,
                threshold_type=InsightThresholdType.PERCENTAGE,
                calculation_interval=AlertCalculationInterval.WEEKLY,
            )
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.calculation_interval == AlertCalculationInterval.WEEKLY

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_with_series_index(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Second series alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=10.0,
                series_index=1,
            )
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.config["series_index"] == 1

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_disabled_alert(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Draft alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
                enabled=False,
            )
        )

        assert "created successfully" in content
        assert "disabled" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.enabled is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_with_skip_weekend(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Weekday only alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
                skip_weekend=True,
            )
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.skip_weekend is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_condition_type_persisted(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Relative increase alert",
                condition_type=AlertConditionType.RELATIVE_INCREASE,
                insight_id=insight.id,
                upper_threshold=0.3,
                threshold_type=InsightThresholdType.PERCENTAGE,
            )
        )

        assert "created successfully" in content
        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.condition == {"type": AlertConditionType.RELATIVE_INCREASE}

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_returns_view_url(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="URL test",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        assert insight.short_id in artifact["alert_url"]
        assert artifact["alert_url"].startswith("/insights/")

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_multiple_alerts_for_same_insight(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content1, artifact1 = await tool._arun_impl(
            action=CreateAlertAction(
                name="Alert one",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
            )
        )
        content2, artifact2 = await tool._arun_impl(
            action=CreateAlertAction(
                name="Alert two",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                upper_threshold=500.0,
            )
        )

        assert "created successfully" in content1
        assert "created successfully" in content2
        assert artifact1["alert_id"] != artifact2["alert_id"]

        count = await sync_to_async(AlertConfiguration.objects.filter(insight=insight).count)()
        assert count == 2

    # -- Create: insight resolution --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_resolve_insight_by_numeric_id(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Numeric ID",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        assert artifact["insight_id"] == insight.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_resolve_insight_by_string_numeric_id(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="String numeric ID",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=str(insight.id),
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        assert artifact["insight_id"] == insight.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_resolve_insight_by_short_id(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Short ID",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.short_id,
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        assert artifact["insight_id"] == insight.id
        assert artifact["insight_short_id"] == insight.short_id

    # -- Create: validation failures --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_non_trends_insight(self):
        insight = await self._create_funnel_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Funnel alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
            )
        )

        assert "not supported" in content.lower()
        assert artifact["error"] == "unsupported_insight"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_no_insight_id(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="No insight alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                lower_threshold=100.0,
            )
        )

        assert "not found" in content.lower()
        assert artifact["error"] == "insight_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_nonexistent_numeric_id(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Missing insight",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=99999,
                lower_threshold=100.0,
            )
        )

        assert "not found" in content.lower()
        assert artifact["error"] == "insight_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_nonexistent_short_id(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Bad short ID",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id="not-a-real-id",
                lower_threshold=100.0,
            )
        )

        assert "not found" in content.lower()
        assert artifact["error"] == "insight_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_no_thresholds(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="No threshold alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
            )
        )

        assert "threshold" in content.lower()
        assert artifact["error"] == "validation_failed"

    # -- Create: cross-team isolation --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_insight_from_other_team(self):
        other_org = await sync_to_async(Organization.objects.create)(name="Other Org")
        other_team = await sync_to_async(Team.objects.create)(organization=other_org, name="Other Team")
        other_insight = await self._create_trends_insight(name="Other Team Insight", team=other_team)

        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Cross-team alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=other_insight.id,
                lower_threshold=100.0,
            )
        )

        assert "not found" in content.lower()
        assert artifact["error"] == "insight_not_found"
        count = await sync_to_async(AlertConfiguration.objects.filter(team=self.team).count)()
        assert count == 0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_insight_from_other_team_via_context(self):
        other_org = await sync_to_async(Organization.objects.create)(name="Other Org")
        other_team = await sync_to_async(Team.objects.create)(organization=other_org, name="Other Team")
        other_insight = await self._create_trends_insight(name="Other Team Insight", team=other_team)

        tool = self._setup_tool(context={"insight_id": other_insight.id})

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Cross-team context alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                lower_threshold=100.0,
            )
        )

        assert "not found" in content.lower()
        assert artifact["error"] == "insight_not_found"
        count = await sync_to_async(AlertConfiguration.objects.filter(team=self.team).count)()
        assert count == 0

    # -- Create: edge cases --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_truncates_long_name(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()
        long_name = "A" * 500

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name=long_name,
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert len(alert.name) == 255

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_negative_threshold(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Negative threshold",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=-50.0,
            )
        )

        assert "created successfully" in content
        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["bounds"]["lower"] == -50.0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_zero_threshold(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Zero threshold",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=insight.id,
                lower_threshold=0.0,
            )
        )

        assert "created successfully" in content
        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["bounds"]["lower"] == 0.0

    # -- Update: happy path --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_name(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, name="Old Name")
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(action=UpdateAlertAction(alert_id=str(alert.id), name="New Name"))

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.name == "New Name"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_threshold(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, lower_threshold=100.0)
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(alert_id=str(alert.id), upper_threshold=200.0)
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["bounds"]["upper"] == 200.0
        assert threshold.configuration["bounds"]["lower"] == 100.0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_enabled(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, enabled=True)
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(action=UpdateAlertAction(alert_id=str(alert.id), enabled=False))

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.enabled is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_condition_type(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, condition_type=AlertConditionType.ABSOLUTE_VALUE)
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(
                alert_id=str(alert.id),
                condition_type=AlertConditionType.RELATIVE_INCREASE,
            )
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.condition == {"type": AlertConditionType.RELATIVE_INCREASE}

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_calculation_interval(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, calculation_interval=AlertCalculationInterval.DAILY)
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(
                alert_id=str(alert.id),
                calculation_interval=AlertCalculationInterval.WEEKLY,
            )
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.calculation_interval == AlertCalculationInterval.WEEKLY

    # -- Update: state reset --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_resets_state_on_threshold_change(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, lower_threshold=100.0)
        await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).update)(state=AlertState.FIRING)

        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(alert_id=str(alert.id), upper_threshold=200.0)
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.state == AlertState.NOT_FIRING
        assert alert.next_check_at is None

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_resets_state_on_condition_change(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, condition_type=AlertConditionType.ABSOLUTE_VALUE)
        await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).update)(state=AlertState.FIRING)

        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(
                alert_id=str(alert.id),
                condition_type=AlertConditionType.RELATIVE_INCREASE,
            )
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.state == AlertState.NOT_FIRING

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_resets_next_check_on_interval_change(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, calculation_interval=AlertCalculationInterval.DAILY)

        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(
                alert_id=str(alert.id),
                calculation_interval=AlertCalculationInterval.WEEKLY,
            )
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.next_check_at is None

    # -- Update: validation failures --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_no_changes(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight)
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(action=UpdateAlertAction(alert_id=str(alert.id)))

        assert "no changes" in content.lower()
        assert artifact["error"] == "no_changes"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_not_found(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(action=UpdateAlertAction(alert_id="99999", name="New Name"))

        assert "not found" in content.lower()
        assert artifact["error"] == "alert_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_cross_team_isolation(self):
        other_org = await sync_to_async(Organization.objects.create)(name="Other Org")
        other_team = await sync_to_async(Team.objects.create)(organization=other_org, name="Other Team")
        other_insight = await self._create_trends_insight(name="Other Insight", team=other_team)

        def _create_other_alert():
            threshold = Threshold.objects.create(
                team=other_team,
                insight=other_insight,
                name="Other Alert",
                configuration={"type": "absolute", "bounds": {"lower": 100}},
                created_by=self.user,
            )
            return AlertConfiguration.objects.create(
                team=other_team,
                insight=other_insight,
                name="Other Alert",
                threshold=threshold,
                condition={"type": AlertConditionType.ABSOLUTE_VALUE},
                config={"type": "TrendsAlertConfig", "series_index": 0},
                calculation_interval=AlertCalculationInterval.DAILY,
                enabled=True,
                created_by=self.user,
            )

        other_alert = await sync_to_async(_create_other_alert)()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(action=UpdateAlertAction(alert_id=str(other_alert.id), name="Hacked"))

        assert "not found" in content.lower()
        assert artifact["error"] == "alert_not_found"

    # -- Update: partial update preserves other fields --

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_partial_update_preserves_other_fields(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(
            insight,
            name="Original",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            lower_threshold=100.0,
            calculation_interval=AlertCalculationInterval.DAILY,
            enabled=True,
        )
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(action=UpdateAlertAction(alert_id=str(alert.id), name="Updated Name"))

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        assert alert.name == "Updated Name"
        assert alert.condition == {"type": AlertConditionType.ABSOLUTE_VALUE}
        assert alert.calculation_interval == AlertCalculationInterval.DAILY
        assert alert.enabled is True

        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["bounds"]["lower"] == 100.0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_threshold_type(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(
            insight,
            lower_threshold=100.0,
            threshold_type=InsightThresholdType.ABSOLUTE,
        )
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(
                alert_id=str(alert.id),
                threshold_type=InsightThresholdType.PERCENTAGE,
                lower_threshold=0.5,
            )
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["type"] == InsightThresholdType.PERCENTAGE
        assert threshold.configuration["bounds"]["lower"] == 0.5

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_rejects_lower_greater_than_upper(self):
        insight = await self._create_trends_insight()
        alert = await self._create_alert(insight, lower_threshold=50.0, upper_threshold=200.0)
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(alert_id=str(alert.id), lower_threshold=300.0)
        )

        assert "lower threshold must be less than upper threshold" in content.lower()
        assert artifact["error"] == "validation_failed"

        # original threshold unchanged
        await sync_to_async(alert.refresh_from_db)()
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["bounds"]["lower"] == 50.0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_moves_threshold_insight_on_insight_change(self):
        insight_a = await self._create_trends_insight(name="Insight A")
        insight_b = await self._create_trends_insight(name="Insight B")
        alert = await self._create_alert(insight_a)
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(alert_id=str(alert.id), insight_id=insight_b.id)
        )

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert await sync_to_async(lambda: threshold.insight_id)() == insight_b.id
