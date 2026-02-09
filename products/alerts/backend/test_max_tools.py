import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import AlertCalculationInterval, AlertConditionType, InsightThresholdType

from posthog.models.alert import AlertConfiguration, AlertSubscription
from posthog.models.insight import Insight

from .max_tools import CreateAlertTool


class TestCreateAlertTool(BaseTest):
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
                    "contextual_tools": {"create_alert": context},
                },
            }
        return CreateAlertTool(team=self.team, user=self.user, config=config)

    async def _create_trends_insight(self, name: str = "Test Insight") -> Insight:
        return await sync_to_async(Insight.objects.create)(
            team=self.team,
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

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_success(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Daily signups below 100",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
            lower_threshold=100.0,
        )

        assert "created successfully" in content
        assert artifact["alert_name"] == "Daily signups below 100"
        assert artifact["insight_id"] == insight.id

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
            name="Value in range",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
            lower_threshold=50.0,
            upper_threshold=200.0,
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
            name="50% increase alert",
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            insight_id=insight.id,
            upper_threshold=0.5,
            threshold_type=InsightThresholdType.PERCENTAGE,
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        threshold = await sync_to_async(lambda: alert.threshold)()
        assert threshold.configuration["type"] == InsightThresholdType.PERCENTAGE
        assert threshold.configuration["bounds"]["upper"] == 0.5

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_rejects_non_trends_insight(self):
        insight = await self._create_funnel_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Funnel alert",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
            lower_threshold=100.0,
        )

        assert "not supported" in content.lower()
        assert artifact["error"] == "unsupported_insight"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_no_insight_id(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="No insight alert",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            lower_threshold=100.0,
        )

        assert "no insight id" in content.lower()
        assert artifact["error"] == "no_insight_id"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_insight_not_found(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Missing insight",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=99999,
            lower_threshold=100.0,
        )

        assert "not found" in content.lower()
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_no_thresholds(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="No threshold alert",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
        )

        assert "threshold" in content.lower()
        assert artifact["error"] == "validation_failed"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_from_context(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool(context={"insight_id": insight.id})

        content, artifact = await tool._arun_impl(
            name="Context-based alert",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            lower_threshold=50.0,
        )

        assert "created successfully" in content
        assert artifact["insight_id"] == insight.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_alert_subscribes_current_user(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Subscription test",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
            lower_threshold=100.0,
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
            name="Weekly alert",
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            insight_id=insight.id,
            lower_threshold=0.2,
            threshold_type=InsightThresholdType.PERCENTAGE,
            calculation_interval=AlertCalculationInterval.WEEKLY,
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
            name="Second series alert",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
            lower_threshold=10.0,
            series_index=1,
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.config["series_index"] == 1

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_when_enabled(self):
        tool = self._setup_tool()

        assert await tool.is_dangerous_operation(enabled=True) is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_not_dangerous_when_disabled(self):
        tool = self._setup_tool()

        assert await tool.is_dangerous_operation(enabled=False) is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_dangerous_operation_preview(self):
        tool = self._setup_tool()

        preview = await tool.format_dangerous_operation_preview(
            name="Daily signups below 100",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            lower_threshold=100.0,
            calculation_interval=AlertCalculationInterval.DAILY,
            threshold_type=InsightThresholdType.ABSOLUTE,
        )

        assert "Daily signups below 100" in preview
        assert "absolute value" in preview
        assert "lower: 100.0" in preview
        assert "daily" in preview
        assert "monitoring" in preview

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_dangerous_operation_preview_percentage(self):
        tool = self._setup_tool()

        preview = await tool.format_dangerous_operation_preview(
            name="50% increase alert",
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            upper_threshold=0.5,
            threshold_type=InsightThresholdType.PERCENTAGE,
            calculation_interval=AlertCalculationInterval.HOURLY,
        )

        assert "50% increase alert" in preview
        assert "relative increase" in preview
        assert "50.0%" in preview
        assert "hourly" in preview

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_disabled_alert(self):
        insight = await self._create_trends_insight()
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Draft alert",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
            lower_threshold=100.0,
            enabled=False,
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
            name="Weekday only alert",
            condition_type=AlertConditionType.ABSOLUTE_VALUE,
            insight_id=insight.id,
            lower_threshold=100.0,
            skip_weekend=True,
        )

        assert "created successfully" in content

        alert = await sync_to_async(AlertConfiguration.objects.get)(id=artifact["alert_id"])
        assert alert.skip_weekend is True
