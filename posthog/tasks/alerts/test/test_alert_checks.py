from typing import Optional
from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from posthog.models.alert import AlertCheck
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.checks import _send_notifications_for_breaches, check_alert
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events, ClickhouseDestroyTablesMixin
from posthog.api.test.dashboards import DashboardAPI
from posthog.schema import ChartDisplayType, EventsNode, TrendsQuery, TrendsFilter, AlertState
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.models import AlertConfiguration


@freeze_time("2024-06-02T08:55:00.000Z")
@patch("posthog.tasks.alerts.checks._send_notifications_for_errors")
@patch("posthog.tasks.alerts.checks._send_notifications_for_breaches")
class TestAlertChecks(APIBaseTest, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                ),
            ],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()

        self.insight = self.dashboard_api.create_insight(
            data={
                "name": "insight",
                "query": query_dict,
            }
        )[1]

        self.alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id],
                "config": {
                    "type": "TrendsAlertConfig",
                    "series_index": 0,
                },
                "threshold": {"configuration": {"absoluteThreshold": {}}},
            },
        ).json()

    def set_thresholds(self, lower: Optional[int] = None, upper: Optional[int] = None) -> None:
        self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{self.alert['id']}",
            data={"threshold": {"configuration": {"absoluteThreshold": {"lower": lower, "upper": upper}}}},
        )

    def get_breach_description(self, mock_send_notifications_for_breaches: MagicMock, call_index: int) -> list[str]:
        return mock_send_notifications_for_breaches.call_args_list[call_index].args[1]

    def test_alert_is_not_triggered_when_disabled(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"enabled": False})

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 0

    def test_alert_is_triggered_for_values_above_higher_threshold(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(upper=0)

        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert = mock_send_notifications_for_breaches.call_args_list[0].args[0]
        assert str(alert.id) == self.alert["id"]

        anomalies_descriptions = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies_descriptions) == 1
        assert "The trend value (1) is above the upper threshold (0.0)" in anomalies_descriptions[0]

    def test_alert_is_not_triggered_for_events_beyond_interval(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(upper=0)

        with freeze_time("2024-05-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 0

    def test_alert_is_triggered_for_value_below_lower_threshold(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert "The trend value (0) is below the lower threshold (1.0)" in anomalies

    def test_alert_triggers_but_does_not_send_notification_during_firing(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        # no events so this should fire
        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert alert.state == AlertState.FIRING

        with freeze_time("2024-06-02T09:00:00.000Z"):
            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 1
            alert = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
            assert alert.state == AlertState.FIRING

        # move to next interval - next day
        with freeze_time("2024-06-03T09:55:00.000Z"):
            self.set_thresholds(lower=0)

            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 1
            assert (
                AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
                == AlertState.NOT_FIRING
            )

        with freeze_time("2024-06-04T11:00:00.000Z"):
            self.set_thresholds(lower=1)

            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 2
            assert (
                AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
                == AlertState.FIRING
            )

        # test clean up old checks (> 14 days)
        with freeze_time("2024-06-20T11:00:00.000Z"):
            AlertCheck.clean_up_old_checks()
            assert AlertCheck.objects.filter(alert_configuration=self.alert["id"]).count() == 0

    def test_alert_is_set_to_not_firing_when_disabled(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert (
            AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
            == AlertState.FIRING
        )

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"enabled": False})

        # Check that the alert is set to inactive and checks are not triggered
        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert AlertConfiguration.objects.get(pk=self.alert["id"]).state == AlertState.NOT_FIRING

    def test_alert_is_set_to_not_firing_when_threshold_changes(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert (
            AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
            == AlertState.FIRING
        )

        self.set_thresholds(lower=2)

        assert AlertConfiguration.objects.get(pk=self.alert["id"]).state == AlertState.NOT_FIRING

    def test_alert_is_not_triggered_for_normal_values(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=0, upper=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 0

    def test_send_error_while_calculating(
        self, _mock_send_notifications_for_breaches: MagicMock, mock_send_notifications_for_errors: MagicMock
    ) -> None:
        with patch(
            "posthog.tasks.alerts.checks.calculate_for_query_based_insight"
        ) as mock_calculate_for_query_based_insight:
            mock_calculate_for_query_based_insight.side_effect = Exception("Some error")

            with freeze_time("2024-06-02T09:00:00.000Z"):
                check_alert(self.alert["id"])
                assert mock_send_notifications_for_errors.call_count == 1

                latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest(
                    "created_at"
                )
                assert latest_alert_check.state == AlertState.ERRORED
                assert latest_alert_check.error["message"] == "Some error"

    def test_error_while_calculating_no_alert_from_firing_state(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_notifications_for_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)
        check_alert(self.alert["id"])
        assert mock_send_notifications_for_breaches.call_count == 1
        assert mock_send_notifications_for_errors.call_count == 0

        latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert latest_alert_check.state == AlertState.FIRING
        assert latest_alert_check.error is None

        with patch(
            "posthog.tasks.alerts.checks.calculate_for_query_based_insight"
        ) as mock_calculate_for_query_based_insight:
            mock_calculate_for_query_based_insight.side_effect = Exception("Some error")

            with freeze_time("2024-06-03T09:00:00.000Z"):
                check_alert(self.alert["id"])
                assert mock_send_notifications_for_breaches.call_count == 1
                assert mock_send_notifications_for_errors.call_count == 1

                latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest(
                    "created_at"
                )
                assert latest_alert_check.state == AlertState.ERRORED
                assert latest_alert_check.error["message"] == "Some error"

    def test_error_while_calculating_no_alert_from_not_firing_state(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_notifications_for_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=0)
        check_alert(self.alert["id"])
        assert mock_send_notifications_for_breaches.call_count == 0
        assert mock_send_notifications_for_errors.call_count == 0

        latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert latest_alert_check.state == AlertState.NOT_FIRING
        assert latest_alert_check.error is None

        with patch(
            "posthog.tasks.alerts.checks.calculate_for_query_based_insight"
        ) as mock_calculate_for_query_based_insight:
            mock_calculate_for_query_based_insight.side_effect = Exception("Some error")

            with freeze_time("2024-06-03T09:00:00.000Z"):
                check_alert(self.alert["id"])
                assert mock_send_notifications_for_breaches.call_count == 0
                assert mock_send_notifications_for_errors.call_count == 1

                latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest(
                    "created_at"
                )
                assert latest_alert_check.state == AlertState.ERRORED
                assert latest_alert_check.error["message"] == "Some error"

    def test_alert_with_insight_with_filter(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.dashboard_api.create_insight(
            data={"name": "insight", "filters": {"events": [{"id": "$pageview"}], "display": "BoldNumber"}}
        )[1]

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"insight": insight["id"]})
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert "The trend value (0) is below the lower threshold (1.0)" in anomalies

    @patch("posthog.tasks.alerts.checks.EmailMessage")
    def test_send_emails(
        self, MockEmailMessage: MagicMock, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        alert = AlertConfiguration.objects.get(pk=self.alert["id"])
        _send_notifications_for_breaches(alert, ["first anomaly description", "second anomaly description"])

        assert len(mocked_email_messages) == 1
        email = mocked_email_messages[0]
        assert len(email.to) == 1
        assert email.to[0]["recipient"] == "user1@posthog.com"
        assert "first anomaly description" in email.html_body
        assert "second anomaly description" in email.html_body

    def test_alert_not_recalculated_when_not_due(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        # no events so this should fire
        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert alert.state == AlertState.FIRING

        with freeze_time("2024-06-02T09:00:00.000Z"):
            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 1
            check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
            assert alert.state == AlertState.FIRING

        # same day for daily alert so won't recalculate as haven't passed next_check_at
        with freeze_time("2024-06-02T09:55:00.000Z"):
            check_alert(self.alert["id"])

            second_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
            # didn't recalculate alert as it was not due
            assert check.id == second_check.id
