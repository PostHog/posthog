from typing import Any, Dict, List
from unittest.mock import ANY, MagicMock, Mock, patch

import pytest
import structlog
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from ee.api.billing import build_billing_token
from ee.api.test.base import LicensedTestMixin
from ee.models.license import License
from ee.settings import BILLING_SERVICE_URL
from posthog.client import sync_execute
from posthog.models import Organization, Plugin, Team, User
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.models.person.util import create_person_distinct_id
from posthog.models.plugin import PluginConfig
from posthog.models.utils import UUIDT
from posthog.session_recordings.test.test_factory import create_snapshot
from posthog.tasks.usage_report import send_all_org_usage_reports
from posthog.test.base import (
    APIBaseTest,
    ClickhouseDestroyTablesMixin,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from posthog.utils import get_machine_id, wait_for_parallel_celery_group

logger = structlog.get_logger(__name__)


def send_all_org_usage_reports_with_wait(*args: Any, **kwargs: Any) -> List[Dict]:
    job = send_all_org_usage_reports(*args, **kwargs)
    wait_for_parallel_celery_group(job)
    return job.get()


@freeze_time("2021-08-25T22:09:14.252Z")
class TestUsageReport(APIBaseTest, ClickhouseTestMixin):
    def _create_new_org_and_team(
        self, for_internal_metrics: bool = False, org_owner_email: str = "test@posthog.com"
    ) -> Team:
        org = Organization.objects.create(name="New Org", for_internal_metrics=for_internal_metrics)
        team = Team.objects.create(organization=org, name="Default Project")
        User.objects.create_and_join(
            organization=org, email=org_owner_email, password=None, level=OrganizationMembership.Level.OWNER
        )
        return team

    def _select_report_by_org_id(self, org_id: str, reports: List[Dict]) -> Dict:
        return [report for report in reports if report["organization_id"] == org_id][0]

    def _create_plugin(self, name: str, enabled: bool) -> None:
        plugin = Plugin.objects.create(organization_id=self.team.organization.pk, name=name)
        PluginConfig.objects.create(plugin=plugin, enabled=enabled, order=1)

    @patch("os.environ", {"DEPLOYMENT": "tests"})
    def test_usage_report(self) -> None:
        with self.settings(SITE_URL="http://test.posthog.com"):
            all_reports = send_all_org_usage_reports_with_wait(dry_run=True)
            report = all_reports[0]

            assert report["table_sizes"]
            assert report["table_sizes"]["posthog_event"] < 10**7  # <10MB
            assert report["table_sizes"]["posthog_sessionrecordingevent"] < 10**7  # <10MB

            assert report == {
                "event_count_lifetime": 3,
                "event_count_in_period": 0,
                "event_count_in_month": 0,
                "event_count_with_groups_in_period": 0,
                "event_count_with_groups_in_month": 0,
                "recording_count_in_period": 0,
                "recording_count_total": 0,
                "using_groups": False,
                "group_types_total": 0,
                "dashboard_count": 0,
                "ff_count": 0,
                "ff_active_count": 0,
                "teams": report["teams"],
                "posthog_version": report["posthog_version"],
                "deployment_infrastructure": "tests",
                "realm": "hosted-clickhouse",
                "period": {
                    "start_inclusive": "2021-08-24T00:00:00+00:00",
                    "end_inclusive": "2021-08-24T23:59:59.999999+00:00",
                },
                "site_url": "http://test.posthog.com",
                "product": "open source",
                "helm": {},
                "clickhouse_version": report["clickhouse_version"],
                "users_who_logged_in": report["users_who_logged_in"],
                "users_who_logged_in_count": None,
                "users_who_signed_up": None,
                "users_who_signed_up_count": None,
                "table_sizes": report["table_sizes"],
                "plugins_installed": {},
                "plugins_enabled": {},
                "date": "2021-08-24",
                "admin_distinct_id": report["admin_distinct_id"],
                "organization_id": str(self.organization.id),
                "organization_name": self.organization.name,
                "organization_created_at": report["organization_created_at"],
                "organization_user_count": 1,
                "team_count": 1,
            }

    def test_event_counts(self) -> None:
        default_team = self._create_new_org_and_team()

        def _test_org_report(org_report: Dict) -> None:
            assert org_report == {
                "event_count_lifetime": 5,
                "event_count_in_period": 3,
                "event_count_in_month": 4,
                "event_count_with_groups_in_period": 0,
                "event_count_with_groups_in_month": 0,
                "recording_count_in_period": 0,
                "recording_count_total": 0,
                "using_groups": False,
                "group_types_total": 0,
                "dashboard_count": 0,
                "ff_count": 0,
                "ff_active_count": 0,
                "teams": org_report["teams"],
                "posthog_version": org_report["posthog_version"],
                "deployment_infrastructure": "unknown",
                "realm": "hosted-clickhouse",
                "period": {
                    "start_inclusive": "2020-11-10T00:00:00+00:00",
                    "end_inclusive": "2020-11-10T23:59:59.999999+00:00",
                },
                "site_url": "http://localhost:8000",
                "product": "open source",
                "helm": {},
                "clickhouse_version": org_report["clickhouse_version"],
                "users_who_logged_in": org_report["users_who_logged_in"],
                "users_who_logged_in_count": None,
                "users_who_signed_up": None,
                "users_who_signed_up_count": None,
                "table_sizes": org_report["table_sizes"],
                "plugins_installed": {},
                "plugins_enabled": {},
                "date": "2020-11-10",
                "admin_distinct_id": org_report["admin_distinct_id"],
                "organization_id": str(default_team.organization.id),
                "organization_name": default_team.organization.name,
                "organization_created_at": org_report["organization_created_at"],
                "organization_user_count": 1,
                "team_count": 1,
            }

        with self.settings(USE_TZ=False):
            with freeze_time("2020-11-10"):
                _create_person(distinct_ids=["old_user1"], team=default_team)
                _create_person(distinct_ids=["old_user2"], team=default_team)

            with freeze_time("2020-11-11 00:30:00"):
                _create_person(distinct_ids=["new_user1"], team=default_team)
                _create_person(distinct_ids=["new_user2"], team=default_team)
                _create_event(
                    distinct_id="new_user1",
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=11),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(hours=11),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(days=1, hours=1),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event3",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(weeks=5),
                    team=default_team,
                )

                all_reports = send_all_org_usage_reports_with_wait(dry_run=True)
                org_report = self._select_report_by_org_id(str(default_team.organization.id), all_reports)
                _test_org_report(org_report)

                # Create usage in a different org.
                team_in_other_org = self._create_new_org_and_team(org_owner_email="other@example.com")
                _create_person(distinct_ids=["new_user1"], team=team_in_other_org)
                _create_person(distinct_ids=["new_user2"], team=team_in_other_org)
                _create_event(
                    distinct_id="new_user1",
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=team_in_other_org,
                )

                # Make sure the original team report is unchanged
                _test_org_report(org_report)

                # Create an event before and after this current period
                _create_event(
                    distinct_id="new_user1",
                    event="$eventAfter",
                    properties={"$lib": "$web"},
                    timestamp=now() + relativedelta(days=2, hours=2),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$eventBefore",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=2, hours=2),
                    team=default_team,
                )

                # Check event totals are updated
                updated_org_reports = send_all_org_usage_reports_with_wait(dry_run=True)
                updated_org_report = self._select_report_by_org_id(
                    str(default_team.organization.id), updated_org_reports
                )
                self.assertEqual(
                    updated_org_report["event_count_lifetime"],
                    org_report["event_count_lifetime"] + 2,
                )

                # Check event usage in current period is unchanged
                self.assertEqual(
                    updated_org_report["event_count_in_period"],
                    org_report["event_count_in_period"],
                )

                # Create an internal metrics org
                internal_metrics_team = self._create_new_org_and_team(
                    for_internal_metrics=True, org_owner_email="hey@posthog.com"
                )
                _create_person(distinct_ids=["new_user1"], team=internal_metrics_team)
                _create_event(
                    distinct_id="new_user1",
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=internal_metrics_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=internal_metrics_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event3",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=internal_metrics_team,
                )

                # Verify that internal metrics events are not counted
                org_reports_after_internal_org = send_all_org_usage_reports_with_wait(dry_run=True)
                org_report_after_internal_org = self._select_report_by_org_id(
                    str(default_team.organization.id), org_reports_after_internal_org
                )
                self.assertEqual(
                    org_report_after_internal_org["event_count_lifetime"],
                    updated_org_report["event_count_lifetime"],
                )

    def test_groups_usage(self) -> None:
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})

        with freeze_time("2021-11-11 00:30:00"):
            _create_event(
                event="event",
                lib="web",
                distinct_id="user_1",
                team=self.team,
                timestamp="2021-11-10 02:00:00",
                properties={"$group_0": "org:5"},
            )
            _create_event(
                event="event",
                lib="web",
                distinct_id="user_1",
                team=self.team,
                timestamp="2021-11-10 05:00:00",
                properties={"$group_0": "org:6"},
            )

            _create_event(
                event="event", lib="web", distinct_id="user_7", team=self.team, timestamp="2021-11-10 10:00:00"
            )

            all_reports = send_all_org_usage_reports_with_wait(dry_run=True)
            org_report = self._select_report_by_org_id(str(self.organization.id), all_reports)

            team_id = list(org_report["teams"].keys())[0]
            self.assertEqual(org_report["teams"][team_id]["group_types_total"], 2)
            self.assertEqual(org_report["event_count_in_period"], 3)
            self.assertEqual(org_report["event_count_with_groups_in_period"], 2)

    def test_recording_usage(self) -> None:
        default_team = self._create_new_org_and_team()
        with freeze_time("2021-11-11 00:30:00"):

            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now() - relativedelta(days=0, hours=2),
                team_id=default_team.id,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now() - relativedelta(days=0, hours=2),
                team_id=default_team.id,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user2",
                session_id="2",
                timestamp=now() - relativedelta(days=0, hours=2),
                team_id=default_team.id,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now() - relativedelta(days=0, hours=2),
                team_id=default_team.id,
            )
            all_reports = send_all_org_usage_reports_with_wait(dry_run=True)
            org_report = self._select_report_by_org_id(str(default_team.organization.id), all_reports)

            self.assertEqual(org_report["recording_count_in_period"], 2)

            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user2",
                session_id="3",
                timestamp=now(),
                team_id=default_team.id,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="4",
                timestamp=now(),
                team_id=default_team.id,
            )
            # Check recording usage in current period is unchanged
            updated_org_reports = send_all_org_usage_reports_with_wait(dry_run=True)
            updated_org_report = self._select_report_by_org_id(str(default_team.organization.id), updated_org_reports)

            self.assertEqual(
                updated_org_report["recording_count_in_period"],
                org_report["recording_count_in_period"],
            )

    def test_status_report_plugins(self) -> None:
        self._create_plugin("Installed but not enabled", False)
        self._create_plugin("Installed and enabled", True)
        all_reports = send_all_org_usage_reports_with_wait(dry_run=True)
        org_report = self._select_report_by_org_id(str(self.organization.id), all_reports)

        self.assertEqual(
            org_report["plugins_installed"],
            {"Installed but not enabled": 1, "Installed and enabled": 1},
        )
        self.assertEqual(org_report["plugins_enabled"], {"Installed and enabled": 1})

    def test_status_report_duplicate_distinct_ids(self) -> None:
        create_person_distinct_id(self.team.id, "duplicate_id1", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id1", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))

        for index in range(0, 2):
            sync_execute(
                "INSERT INTO person_distinct_id SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, 1, %(timestamp)s, 0 VALUES",
                {
                    "distinct_id": "duplicate_id_old",
                    "person_id": str(UUIDT()),
                    "team_id": self.team.id,
                    "timestamp": "2020-01-01 12:01:0%s" % index,
                },
            )

        all_reports = send_all_org_usage_reports_with_wait(dry_run=True)
        report = all_reports[0]
        team_id = list(report["teams"].keys())[0]
        team_report = report["teams"][team_id]

        duplicate_ids_report = team_report["duplicate_distinct_ids"]

        expected_result = {
            "prev_total_ids_with_duplicates": 1,
            "prev_total_extra_distinct_id_rows": 1,
            "new_total_ids_with_duplicates": 2,
            "new_total_extra_distinct_id_rows": 4,
        }

        self.assertEqual(duplicate_ids_report, expected_result)

    # CH only
    def test_status_report_multiple_ids_per_person(self) -> None:
        person_id1 = str(UUIDT())
        person_id2 = str(UUIDT())

        create_person_distinct_id(self.team.id, "id1", person_id1)
        create_person_distinct_id(self.team.id, "id2", person_id1)
        create_person_distinct_id(self.team.id, "id3", person_id1)
        create_person_distinct_id(self.team.id, "id4", person_id1)
        create_person_distinct_id(self.team.id, "id5", person_id1)

        create_person_distinct_id(self.team.id, "id6", person_id2)
        create_person_distinct_id(self.team.id, "id7", person_id2)
        create_person_distinct_id(self.team.id, "id8", person_id2)

        all_reports = send_all_org_usage_reports_with_wait(dry_run=True)
        report = all_reports[0]
        team_id = list(report["teams"].keys())[0]
        team_report = report["teams"][team_id]

        multiple_ids_report = team_report["multiple_ids_per_person"]

        expected_result = {"total_persons_with_more_than_2_ids": 2, "max_distinct_ids_for_one_person": 5}

        self.assertEqual(multiple_ids_report, expected_result)


class SendUsageTest(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.team2 = Team.objects.create(organization=self.organization)

        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-08T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T12:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T13:01:01Z")
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(event="$pageview", team=self.team2, distinct_id=1, timestamp="2021-10-09T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-10T14:01:01Z")
        flush_persons_and_events()

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_send_usage(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.status_code = 200
        mockresponse.json = lambda: {"ok": True}
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        all_reports = send_all_org_usage_reports_with_wait(dry_run=False)
        license = License.objects.first()
        assert license
        token = build_billing_token(license, self.organization)
        mock_post.assert_called_once_with(
            f"{BILLING_SERVICE_URL}/api/usage", json=all_reports[0], headers={"Authorization": f"Bearer {token}"}
        )

        mock_posthog.capture.assert_any_call(
            get_machine_id(),
            "organization usage report",
            {**all_reports[0], "scope": "machine"},
            groups={"instance": ANY},
            timestamp=None,
        )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_send_usage_cloud(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        with self.is_cloud(True):
            mockresponse = Mock()
            mock_post.return_value = mockresponse
            mockresponse.status_code = 200
            mockresponse.json = lambda: {"ok": True}
            mock_posthog = MagicMock()
            mock_client.return_value = mock_posthog

            all_reports = send_all_org_usage_reports_with_wait(dry_run=False)
            license = License.objects.first()
            assert license
            token = build_billing_token(license, self.organization)
            mock_post.assert_called_once_with(
                f"{BILLING_SERVICE_URL}/api/usage", json=all_reports[0], headers={"Authorization": f"Bearer {token}"}
            )

            mock_posthog.capture.assert_any_call(
                self.user.distinct_id,
                "organization usage report",
                {**all_reports[0], "scope": "user"},
                groups={"instance": "http://localhost:8000", "organization": str(self.organization.id)},
                timestamp=None,
            )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_send_usage_billing_service_not_reachable(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.status_code = 404
        mockresponse.ok = False
        mockresponse.json = lambda: {"code": "not_found"}
        mockresponse.content = ""

        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        send_all_org_usage_reports_with_wait(dry_run=False)
        mock_posthog.capture.assert_any_call(
            get_machine_id(),
            "billing service usage report failure",
            {"code": 404, "scope": "machine"},
            groups={"instance": ANY},
            timestamp=None,
        )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.get_org_usage_report")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_send_usage_backup(
        self, mock_post: MagicMock, mock_client: MagicMock, mock_get_org_usage_report: MagicMock
    ) -> None:
        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.status_code = 200
        mockresponse.json = lambda: {"ok": True}
        mock_get_org_usage_report.side_effect = Exception("something went wrong")

        with pytest.raises(Exception):
            send_all_org_usage_reports_with_wait(dry_run=False)
        license = License.objects.first()
        assert license
        token = build_billing_token(license, self.organization)
        mock_post.assert_called_once_with(
            f"{BILLING_SERVICE_URL}/api/usage",
            json={
                "organization_id": str(self.organization.id),
                "date": "2021-10-09",
                "event_count_in_period": 4,
                "recording_count_in_period": 0,
            },
            headers={"Authorization": f"Bearer {token}"},
        )


class SendUsageNoLicenseTest(APIBaseTest):
    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_no_license(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        # Same test, we just don't include the LicensedTestMixin so no license
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-08T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T12:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T13:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T14:01:01Z")
        _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-10T14:01:01Z")

        flush_persons_and_events()

        all_reports = send_all_org_usage_reports_with_wait()

        mock_post.assert_called_once_with(f"{BILLING_SERVICE_URL}/api/usage", json=all_reports[0], headers={})
