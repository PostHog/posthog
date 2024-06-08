import pytest
from typing import Optional
from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from posthog.models.instance_setting import set_instance_setting
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events, ClickhouseDestroyTablesMixin
from posthog.api.test.dashboards import DashboardAPI
from posthog.schema import ChartDisplayType, EventsNode, TrendsQuery, TrendsFilter
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.tasks.detect_alerts_anomalies import check_all_alerts


@freeze_time("2024-06-02T08:55:00.000Z")
@patch("posthog.tasks.detect_alerts_anomalies.EmailMessage")
class TestDetectAlertsAnomaliesTasks(APIBaseTest, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.settings(CELERY_TASK_ALWAYS_EAGER=True)
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                ),
            ],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BoldNumber),
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
                "target_value": "a@b.c,d@e.f",
                "anomaly_condition": {"absoluteThreshold": {}},
            },
        ).json()

    def set_thresholds(self, lower: Optional[int] = None, upper: Optional[int] = None):
        self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{self.alert['id']}",
            data={"anomaly_condition": {"absoluteThreshold": {"lower": lower, "upper": upper}}},
        )

    def get_recepients(self, mocked_email_messages) -> list[list[str]]:
        recipients = [sorted([to["recipient"] for to in message.to]) for message in mocked_email_messages]
        return sorted(recipients)

    def test_alert_is_triggered_for_values_above_higher_threshold(self, MockEmailMessage: MagicMock):
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        self.set_thresholds(upper=0)

        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_all_alerts()

        assert len(mocked_email_messages) == 1
        assert self.get_recepients(mocked_email_messages) == [["a@b.c", "d@e.f"]]
        assert "The trend value (1) is above the upper threshold (0)" in mocked_email_messages[0].html_body

    def test_alert_is_triggered_for_value_below_lower_threshold(self, MockEmailMessage: MagicMock):
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        self.set_thresholds(lower=1)

        check_all_alerts()

        assert len(mocked_email_messages) == 1
        assert "The trend value (0) is below the lower threshold (1)" in mocked_email_messages[0].html_body

    def test_alert_is_not_triggered_for_normal_values(self, MockEmailMessage: MagicMock):
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        self.set_thresholds(lower=0, upper=1)

        check_all_alerts()

        assert len(mocked_email_messages) == 0

    def test_error_while_calculating_no_alert(self, MockEmailMessage: MagicMock):
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                ),
            ],
        ).model_dump()
        insight = self.dashboard_api.create_insight(
            data={
                "name": "insight",
                "query": query_dict,
            }
        )[1]

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"insight": insight["id"]})

        # in production one alert failure won't cause an exception in check_all_alerts
        # because execution won't be eager (see CELERY_TASK_ALWAYS_EAGER in the set up)
        with pytest.raises(KeyError):
            check_all_alerts()

        assert len(mocked_email_messages) == 0

    def test_two_alerts_are_triggered(self, MockEmailMessage: MagicMock):
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        self.set_thresholds(lower=1)
        self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "another alert name",
                "insight": self.insight["id"],
                "target_value": "email@address.com",
                "anomaly_condition": {"absoluteThreshold": {"lower": 1}},
            },
        ).json()

        check_all_alerts()

        assert len(mocked_email_messages) == 2
        assert "The trend value (0) is below the lower threshold (1)" in mocked_email_messages[0].html_body
        assert "The trend value (0) is below the lower threshold (1)" in mocked_email_messages[1].html_body
        assert self.get_recepients(mocked_email_messages) == [["a@b.c", "d@e.f"], ["email@address.com"]]

    def test_alert_with_insight_with_filter(self, MockEmailMessage: MagicMock):
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        insight = self.dashboard_api.create_insight(
            data={"name": "insight", "filters": {"events": [{"id": "$pageview"}], "display": "BoldNumber"}}
        )[1]

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"insight": insight["id"]})
        self.set_thresholds(lower=1)

        check_all_alerts()

        assert len(mocked_email_messages) == 1
        assert "The trend value (0) is below the lower threshold (1)" in mocked_email_messages[0].html_body
