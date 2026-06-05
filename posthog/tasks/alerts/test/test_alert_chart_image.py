from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.tasks.alerts.utils import (
    CHART_IMAGE_URL_PROPERTY,
    INSIGHT_ALERT_FIRING_EVENT,
    alert_has_slack_destination,
    generate_alert_chart_image_url,
    send_notifications_for_breaches,
)

from products.alerts.backend.models.alert import AlertConfiguration
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType
from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.models.insight import Insight

SLACK_FILTERS = {"events": [{"id": INSIGHT_ALERT_FIRING_EVENT, "type": "events"}]}
# Mirrors the sub-template: blocks that template the chart image URL.
CHART_INPUTS = {
    "blocks": {"value": [{"type": "image", "image_url": f"{{event.properties.{CHART_IMAGE_URL_PROPERTY}}}"}]}
}


def _filters_scoped_to_alert(alert_id: str) -> dict:
    return {
        "events": [{"id": INSIGHT_ALERT_FIRING_EVENT, "type": "events"}],
        "properties": [{"key": "alert_id", "value": alert_id, "operator": "exact", "type": "event"}],
    }


class TestAlertChartImage(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="signups")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            enabled=True,
            created_by=self.user,
        )

    def _create_slack_destination(
        self,
        *,
        enabled: bool = True,
        deleted: bool = False,
        template_id: str = "template-slack",
        type: str = HogFunctionType.INTERNAL_DESTINATION,
        filters: dict | None = None,
        inputs: dict | None = None,
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            type=type,
            template_id=template_id,
            enabled=enabled,
            deleted=deleted,
            filters=SLACK_FILTERS if filters is None else filters,
            # inputs_schema must declare `blocks` or HogFunction.save() drops it (move_secret_inputs).
            inputs_schema=[{"key": "blocks", "type": "json"}],
            inputs=CHART_INPUTS if inputs is None else inputs,
        )

    def test_no_destinations_means_no_slack(self) -> None:
        assert alert_has_slack_destination(self.alert) is False

    def test_team_wide_slack_destination_detected(self) -> None:
        # No alert_id property filter — applies to every alert on the team.
        self._create_slack_destination()
        assert alert_has_slack_destination(self.alert) is True

    def test_destination_scoped_to_this_alert_detected(self) -> None:
        self._create_slack_destination(filters=_filters_scoped_to_alert(str(self.alert.id)))
        assert alert_has_slack_destination(self.alert) is True

    def test_destination_scoped_to_other_alert_ignored(self) -> None:
        other_alert = AlertConfiguration.objects.create(
            team=self.team, insight=self.insight, name="other", enabled=True, created_by=self.user
        )
        self._create_slack_destination(filters=_filters_scoped_to_alert(str(other_alert.id)))
        assert alert_has_slack_destination(self.alert) is False

    def test_destination_without_chart_block_ignored(self) -> None:
        # Pre-existing Slack destination whose stored blocks don't template the chart URL.
        self._create_slack_destination(inputs={"blocks": {"value": [{"type": "section", "text": "hi"}]}})
        assert alert_has_slack_destination(self.alert) is False

    @parameterized.expand(
        [
            ("disabled", {"enabled": False}),
            ("deleted", {"deleted": True}),
            ("webhook_template", {"template_id": "template-webhook"}),
            ("regular_destination", {"type": HogFunctionType.DESTINATION}),
            ("different_event", {"filters": {"events": [{"id": "$other_event", "type": "events"}]}}),
        ]
    )
    def test_non_matching_destinations_ignored(self, _name: str, overrides: dict) -> None:
        self._create_slack_destination(**overrides)
        assert alert_has_slack_destination(self.alert) is False

    def test_destination_for_other_team_ignored(self) -> None:
        other_team = self.organization.teams.create(name="other")
        HogFunction.objects.create(
            team=other_team,
            type=HogFunctionType.INTERNAL_DESTINATION,
            template_id="template-slack",
            enabled=True,
            filters=SLACK_FILTERS,
        )
        assert alert_has_slack_destination(self.alert) is False

    @patch("posthog.tasks.alerts.utils.produce_internal_event")
    @patch(
        "posthog.tasks.alerts.utils.generate_alert_chart_image_url", return_value="https://app/exporter/x.png?token=t"
    )
    def test_chart_image_url_attached_when_slack_destination_exists(
        self, mock_generate: MagicMock, mock_produce: MagicMock
    ) -> None:
        self._create_slack_destination()

        send_notifications_for_breaches(self.alert, ["value 5 is above 1"], idempotency_key="key")

        mock_generate.assert_called_once_with(self.alert)
        props = mock_produce.call_args.kwargs["event"].properties
        assert props["chart_image_url"] == "https://app/exporter/x.png?token=t"
        assert props["breaches"] == "value 5 is above 1"

    @patch("posthog.tasks.alerts.utils.produce_internal_event")
    @patch("posthog.tasks.alerts.utils.generate_alert_chart_image_url")
    def test_no_render_without_slack_destination(self, mock_generate: MagicMock, mock_produce: MagicMock) -> None:
        send_notifications_for_breaches(self.alert, ["value 5 is above 1"], idempotency_key="key")

        mock_generate.assert_not_called()
        props = mock_produce.call_args.kwargs["event"].properties
        assert "chart_image_url" not in props

    @patch("posthog.tasks.alerts.utils.produce_internal_event")
    @patch("posthog.tasks.alerts.utils.generate_alert_chart_image_url", return_value=None)
    def test_render_failure_does_not_attach_url(self, mock_generate: MagicMock, mock_produce: MagicMock) -> None:
        self._create_slack_destination()

        send_notifications_for_breaches(self.alert, ["value 5 is above 1"], idempotency_key="key")

        mock_generate.assert_called_once_with(self.alert)
        props = mock_produce.call_args.kwargs["event"].properties
        assert "chart_image_url" not in props

    @patch("posthog.tasks.alerts.utils.export_asset_direct")
    def test_generate_chart_image_creates_system_png_asset(self, mock_export: MagicMock) -> None:
        url = generate_alert_chart_image_url(self.alert)

        asset = ExportedAsset.objects.get(insight=self.insight)
        assert asset.export_format == ExportedAsset.ExportFormat.PNG
        assert asset.is_system is True
        assert asset.team == self.team
        mock_export.assert_called_once()
        assert url is not None and asset.filename in url

    @patch("posthog.tasks.alerts.utils.export_asset_direct", side_effect=RuntimeError("browser crashed"))
    def test_generate_chart_image_returns_url_even_if_render_fails(self, mock_export: MagicMock) -> None:
        # Asset is created before the render, so the URL is still valid for Slack to fetch.
        url = generate_alert_chart_image_url(self.alert)

        assert ExportedAsset.objects.filter(insight=self.insight).exists()
        assert url is not None
