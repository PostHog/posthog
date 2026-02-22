import pytest
from posthog.test.base import BaseTest
from unittest import mock

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

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

    async def _create_insight(
        self, name: str = "Test Insight", team: Team | None = None, query_kind: str = "TrendsQuery"
    ) -> Insight:
        return await sync_to_async(Insight.objects.create)(
            team=team or self.team,
            name=name,
            created_by=self.user,
            query={
                "kind": "InsightVizNode",
                "source": {"kind": query_kind, "series": [{"kind": "EventsNode", "event": "$pageview"}]},
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

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_success(self):
        insight = await self._create_insight()
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
        assert insight.short_id in artifact["alert_url"]
        assert artifact["alert_url"].startswith("/insights/")

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.name == "Daily signups below 100"
        assert alert.enabled is True
        assert alert.calculation_interval == AlertCalculationInterval.DAILY

        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold is not None
        assert threshold.configuration["bounds"]["lower"] == 100.0
        assert threshold.configuration["type"] == InsightThresholdType.ABSOLUTE

        subscription = await sync_to_async(AlertSubscription.objects.get)(alert_configuration=alert)
        assert subscription.user_id == self.user.id

    @parameterized.expand(
        [
            (
                "both_bounds",
                {"lower_threshold": 50.0, "upper_threshold": 200.0},
                lambda alert, threshold: (
                    threshold.configuration["bounds"]["lower"] == 50.0
                    and threshold.configuration["bounds"]["upper"] == 200.0
                ),
            ),
            (
                "percentage_threshold",
                {
                    "condition_type": AlertConditionType.RELATIVE_INCREASE,
                    "upper_threshold": 0.5,
                    "threshold_type": InsightThresholdType.PERCENTAGE,
                },
                lambda alert, threshold: (
                    threshold.configuration["type"] == InsightThresholdType.PERCENTAGE
                    and threshold.configuration["bounds"]["upper"] == 0.5
                    and alert.condition == {"type": AlertConditionType.RELATIVE_INCREASE}
                ),
            ),
            (
                "weekly_interval",
                {"lower_threshold": 100.0, "calculation_interval": AlertCalculationInterval.WEEKLY},
                lambda alert, threshold: alert.calculation_interval == AlertCalculationInterval.WEEKLY,
            ),
            (
                "series_index",
                {"lower_threshold": 10.0, "series_index": 1},
                lambda alert, threshold: alert.config is not None and alert.config["series_index"] == 1,
            ),
            (
                "disabled",
                {"lower_threshold": 100.0, "enabled": False},
                lambda alert, threshold: alert.enabled is False,
            ),
            (
                "skip_weekend",
                {"lower_threshold": 100.0, "skip_weekend": True},
                lambda alert, threshold: alert.skip_weekend is True,
            ),
            (
                "negative_threshold",
                {"lower_threshold": -50.0},
                lambda alert, threshold: threshold.configuration["bounds"]["lower"] == -50.0,
            ),
            (
                "zero_threshold",
                {"lower_threshold": 0.0},
                lambda alert, threshold: threshold.configuration["bounds"]["lower"] == 0.0,
            ),
            (
                "long_name_truncated",
                {"lower_threshold": 100.0, "name": "A" * 500},
                lambda alert, threshold: len(alert.name) == 255,
            ),
        ]
    )
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_with_option(self, _name, extra_kwargs, check):
        insight = await self._create_insight()
        tool = self._setup_tool()

        action_kwargs = {
            "name": f"Alert {_name}",
            "condition_type": AlertConditionType.ABSOLUTE_VALUE,
            "insight_id": insight.id,
            **extra_kwargs,
        }

        content, artifact = await tool._arun_impl(action=CreateAlertAction(**action_kwargs))

        assert "created successfully" in content
        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold is not None
        assert check(alert, threshold), f"Check failed for {_name}"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_from_context(self):
        insight = await self._create_insight()
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
    async def test_create_multiple_alerts_for_same_insight(self):
        insight = await self._create_insight()
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

    @parameterized.expand(
        [
            ("numeric_id", lambda i: i.id),
            ("string_numeric_id", lambda i: str(i.id)),
            ("short_id", lambda i: i.short_id),
        ]
    )
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_resolve_insight_by(self, _name, get_id):
        insight = await self._create_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            action=CreateAlertAction(
                name="Resolve test",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=get_id(insight),
                lower_threshold=100.0,
            )
        )

        assert "created successfully" in content
        assert artifact["insight_id"] == insight.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_non_trends_insight(self):
        insight = await self._create_insight(query_kind="FunnelsQuery")
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

    @parameterized.expand(
        [
            ("no_id", None),
            ("nonexistent_numeric_id", -999),
            ("nonexistent_short_id", "not-a-real-id"),
        ]
    )
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_bad_insight_id(self, _name, insight_id):
        tool = self._setup_tool()

        kwargs: dict = {
            "name": "Bad insight",
            "condition_type": AlertConditionType.ABSOLUTE_VALUE,
            "lower_threshold": 100.0,
        }
        if insight_id is not None:
            kwargs["insight_id"] = insight_id

        content, artifact = await tool._arun_impl(action=CreateAlertAction(**kwargs))

        assert "not found" in content.lower()
        assert artifact["error"] == "insight_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_no_thresholds(self):
        insight = await self._create_insight()
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

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_when_alert_limit_reached(self):
        insight = await self._create_insight()
        await self._create_alert(insight)
        tool = self._setup_tool()

        with mock.patch.object(AlertConfiguration, "ALERTS_ALLOWED_ON_FREE_TIER", 1):
            content, artifact = await tool._arun_impl(
                action=CreateAlertAction(
                    name="Over limit",
                    condition_type=AlertConditionType.ABSOLUTE_VALUE,
                    insight_id=insight.id,
                    lower_threshold=100.0,
                )
            )

        assert "limited to 1 alerts" in content.lower()
        assert artifact["error"] == "plan_limit_reached"

    @parameterized.expand(
        [
            ("via_explicit_id", False),
            ("via_context", True),
        ]
    )
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_insight_from_other_team(self, _name, use_context):
        other_org = await sync_to_async(Organization.objects.create)(name="Other Org")
        other_team = await sync_to_async(Team.objects.create)(organization=other_org, name="Other Team")
        other_insight = await self._create_insight(name="Other Team Insight", team=other_team)

        if use_context:
            tool = self._setup_tool(context={"insight_id": other_insight.id})
            action = CreateAlertAction(
                name="Cross-team alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                lower_threshold=100.0,
            )
        else:
            tool = self._setup_tool()
            action = CreateAlertAction(
                name="Cross-team alert",
                condition_type=AlertConditionType.ABSOLUTE_VALUE,
                insight_id=other_insight.id,
                lower_threshold=100.0,
            )

        content, artifact = await tool._arun_impl(action=action)

        assert "not found" in content.lower()
        assert artifact["error"] == "insight_not_found"
        count = await sync_to_async(AlertConfiguration.objects.filter(team=self.team).count)()
        assert count == 0

    @parameterized.expand(
        [
            # Field updates
            (
                "name",
                {"name": "Old Name"},
                {"name": "New Name"},
                lambda a, t: a.name == "New Name",
            ),
            (
                "enabled",
                {"enabled": True},
                {"enabled": False},
                lambda a, t: a.enabled is False,
            ),
            (
                "condition_type",
                {"condition_type": AlertConditionType.ABSOLUTE_VALUE},
                {"condition_type": AlertConditionType.RELATIVE_INCREASE},
                lambda a, t: a.condition == {"type": AlertConditionType.RELATIVE_INCREASE},
            ),
            (
                "calculation_interval",
                {"calculation_interval": AlertCalculationInterval.DAILY},
                {"calculation_interval": AlertCalculationInterval.WEEKLY},
                lambda a, t: a.calculation_interval == AlertCalculationInterval.WEEKLY,
            ),
            # Threshold updates
            (
                "add_upper_bound",
                {"lower_threshold": 100.0},
                {"upper_threshold": 200.0},
                lambda a, t: (
                    t.configuration["bounds"]["lower"] == 100.0 and t.configuration["bounds"]["upper"] == 200.0
                ),
            ),
            (
                "change_threshold_type",
                {"lower_threshold": 100.0, "threshold_type": InsightThresholdType.ABSOLUTE},
                {"threshold_type": InsightThresholdType.PERCENTAGE, "lower_threshold": 0.5},
                lambda a, t: (
                    t.configuration["type"] == InsightThresholdType.PERCENTAGE
                    and t.configuration["bounds"]["lower"] == 0.5
                ),
            ),
            # Recheck side effects
            (
                "threshold_change_resets_state",
                {"lower_threshold": 100.0},
                {"upper_threshold": 200.0},
                lambda a, t: a.state == AlertState.NOT_FIRING and a.next_check_at is None,
            ),
            (
                "condition_change_resets_state",
                {"condition_type": AlertConditionType.ABSOLUTE_VALUE},
                {"condition_type": AlertConditionType.RELATIVE_INCREASE},
                lambda a, t: a.state == AlertState.NOT_FIRING and a.next_check_at is None,
            ),
            (
                "interval_change_clears_next_check_only",
                {"calculation_interval": AlertCalculationInterval.DAILY},
                {"calculation_interval": AlertCalculationInterval.WEEKLY},
                lambda a, t: a.state == AlertState.FIRING and a.next_check_at is None,
            ),
        ]
    )
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert(self, _name, create_kwargs, update_kwargs, check):
        insight = await self._create_insight()
        alert = await self._create_alert(insight, **create_kwargs)
        await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).update)(state=AlertState.FIRING)

        tool = self._setup_tool()
        content, artifact = await tool._arun_impl(action=UpdateAlertAction(alert_id=str(alert.id), **update_kwargs))

        assert "updated successfully" in content
        await sync_to_async(alert.refresh_from_db)()
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert check(alert, threshold), f"Check failed for {_name}"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_no_changes(self):
        insight = await self._create_insight()
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
        other_insight = await self._create_insight(name="Other Insight", team=other_team)

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

        content, artifact = await tool._arun_impl(
            action=UpdateAlertAction(alert_id=str(other_alert.id), name="Hijacked")
        )

        assert "not found" in content.lower()
        assert artifact["error"] == "alert_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_partial_update_preserves_other_fields(self):
        insight = await self._create_insight()
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
        assert threshold is not None
        assert threshold.configuration["bounds"]["lower"] == 100.0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_alert_rejects_lower_greater_than_upper(self):
        insight = await self._create_insight()
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
        assert threshold is not None
        assert threshold.configuration["bounds"]["lower"] == 50.0
