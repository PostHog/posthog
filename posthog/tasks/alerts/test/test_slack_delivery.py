from types import SimpleNamespace

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ChartDisplayType, EventsNode, TrendsFilter, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.slack_delivery import (
    _latest_slack_config_failure,
    _match_slack_config_error,
    check_and_notify_slack_delivery_failures,
)
from posthog.tasks.test.utils_email_tests import mock_email_messages

from products.alerts.backend.models import AlertConfiguration
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

# The raw error the Slack HogFunction template throws embeds the Slack error code inside a
# stringified response body, so matching must substring-scan — not compare against error_kind.
_NOT_IN_CHANNEL_MESSAGE = 'Failed to post message to Slack: 200: {"ok":false,"error":"not_in_channel"}'
_INVALID_AUTH_MESSAGE = 'Failed to post message to Slack: 200: {"ok":false,"error":"invalid_auth"}'
_RATELIMITED_MESSAGE = 'Failed to post message to Slack: 429: {"ok":false,"error":"ratelimited"}'


class TestSlackErrorMatching(TestCase):
    @parameterized.expand(
        [
            ("not_in_channel_in_body", _NOT_IN_CHANNEL_MESSAGE, "not_in_channel"),
            ("invalid_auth_in_body", _INVALID_AUTH_MESSAGE, "invalid_auth"),
            ("channel_not_found", "boom channel_not_found boom", "channel_not_found"),
            ("case_insensitive", "TOKEN_REVOKED", "token_revoked"),
            ("transient_ratelimited_not_matched", _RATELIMITED_MESSAGE, None),
            ("unrelated_error_not_matched", "Failed to post message to Slack: 500: internal_error", None),
            ("empty", "", None),
            ("none", None, None),
        ]
    )
    def test_match_slack_config_error(self, _name: str, message: str | None, expected: str | None) -> None:
        assert _match_slack_config_error(message) == expected


class TestLatestSlackConfigFailure(TestCase):
    @parameterized.expand(
        [
            ("latest_failed_config_error", "failed", _NOT_IN_CHANNEL_MESSAGE, "not_in_channel"),
            ("latest_failed_transient", "failed", _RATELIMITED_MESSAGE, None),
            ("latest_succeeded", "success", "", None),
        ]
    )
    @patch("posthog.tasks.alerts.slack_delivery.fetch_hog_invocation_results")
    def test_reads_current_delivery_state(
        self, _name: str, status: str, message: str, expected: str | None, mock_fetch: MagicMock
    ) -> None:
        # Only the single most recent invocation is inspected — a since-recovered destination
        # (latest success) must not keep alerting even if older runs failed.
        mock_fetch.return_value = [SimpleNamespace(status=status, error_message=message)]
        assert _latest_slack_config_failure(team_id=1, function_id="fn") == expected
        assert mock_fetch.call_args.kwargs["limit"] == 1

    @patch("posthog.tasks.alerts.slack_delivery.fetch_hog_invocation_results")
    def test_no_invocations_returns_none(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = []
        assert _latest_slack_config_failure(team_id=1, function_id="fn") is None

    @patch("posthog.tasks.alerts.slack_delivery.fetch_hog_invocation_results")
    def test_query_failure_is_swallowed(self, mock_fetch: MagicMock) -> None:
        # A ClickHouse hiccup in this observability lookup must never break the notification path.
        mock_fetch.side_effect = Exception("clickhouse down")
        assert _latest_slack_config_failure(team_id=1, function_id="fn") is None


@freeze_time("2024-06-02T08:55:00.000Z")
class TestCheckAndNotifySlackDeliveryFailures(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()
        self.insight = self.dashboard_api.create_insight(data={"name": "insight", "query": query_dict})[1]

        alert_response = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 0}}},
            },
        ).json()
        self.alert = AlertConfiguration.objects.get(pk=alert_response["id"])

    def _link_hog_function(self, alert_id: str) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Slack notification for alert",
            type="internal_destination",
            hog="return 1",
            enabled=True,
            filters={
                "events": [{"id": "$insight_alert_firing", "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id, "operator": "exact", "type": "event"}],
            },
        )

    @patch("posthog.tasks.alerts.slack_delivery.EmailMessage")
    @patch("posthog.tasks.alerts.slack_delivery.fetch_hog_invocation_results")
    def test_emails_owner_when_linked_slack_delivery_failed(
        self, mock_fetch: MagicMock, MockEmailMessage: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        mock_fetch.return_value = [SimpleNamespace(status="failed", error_message=_NOT_IN_CHANNEL_MESSAGE)]
        hog_function = self._link_hog_function(str(self.alert.id))

        check_and_notify_slack_delivery_failures(self.alert)

        assert len(mocked_email_messages) == 1
        email = mocked_email_messages[0]
        assert email.campaign_key == f"alert-slack-delivery-failure-{self.alert.id}-{hog_function.id}-not_in_channel"
        assert [r["recipient"] for r in email.to] == ["user1@posthog.com"]

    @patch("posthog.tasks.alerts.slack_delivery.EmailMessage")
    @patch("posthog.tasks.alerts.slack_delivery.fetch_hog_invocation_results")
    def test_does_not_email_for_unrelated_destination(self, mock_fetch: MagicMock, MockEmailMessage: MagicMock) -> None:
        # A destination linked to a different alert must not be matched — guards the alert_id filter.
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        self._link_hog_function("some-other-alert-id")

        check_and_notify_slack_delivery_failures(self.alert)

        assert len(mocked_email_messages) == 0
        mock_fetch.assert_not_called()
