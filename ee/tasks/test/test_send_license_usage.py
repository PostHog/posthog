from unittest.mock import ANY, patch

from freezegun import freeze_time

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.util import ClickhouseDestroyTablesMixin
from ee.tasks.send_license_usage import send_license_usage
from posthog.models.team import Team
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events


class SendLicenseUsageTest(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthoganalytics.capture")
    @patch("requests.post")
    def test_send_license_usage(self, mock_post, mock_capture):
        team2 = Team.objects.create(organization=self.organization)
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-08T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T12:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T13:01:01Z")
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(event="$pageview", team=team2, distinct_id=1, timestamp="2021-10-09T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-10T14:01:01Z")
        flush_persons_and_events()

        send_license_usage()
        mock_post.assert_called_once_with(
            "https://license.posthog.com/licenses/usage",
            data={"date": "2021-10-09", "key": self.license.key, "events_count": 3},
        )
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "send license usage data",
            {"date": "2021-10-09", "events_count": 3, "license_keys": ["enterprise"], "organization_name": "Test"},
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthoganalytics.capture")
    @patch("ee.tasks.send_license_usage.sync_execute", side_effect=Exception())
    def test_send_license_error(self, mock_post, mock_capture):
        team2 = Team.objects.create(organization=self.organization)
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-08T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T12:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T13:01:01Z")
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(event="$pageview", team=team2, distinct_id=1, timestamp="2021-10-09T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-10T14:01:01Z")
        flush_persons_and_events()
        send_license_usage()
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "send license usage data error",
            {"error": "", "date": "2021-10-09", "organization_name": "Test"},
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )


class SendLicenseUsageNoLicenseTest(APIBaseTest):
    @freeze_time("2021-10-10T23:01:00Z")
    @patch("requests.post")
    def test_no_license(self, mock_post):
        # Same test, we just don't include the LicensedTestMixin so no license
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-08T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T12:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T13:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-10T14:01:01Z")

        flush_persons_and_events()

        send_license_usage()

        self.assertEqual(mock_post.call_count, 0)
