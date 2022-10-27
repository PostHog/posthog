from typing import Any, Dict, List
from unittest.mock import ANY, MagicMock, Mock, patch
from uuid import uuid4

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
from posthog.tasks.usage_report_v2 import send_all_org_usage_reports
from posthog.test.base import (
    APIBaseTest,
    ClickhouseDestroyTablesMixin,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from posthog.utils import get_machine_id

logger = structlog.get_logger(__name__)


@freeze_time("2022-01-10T00:01:00Z")
class TestUsageReport(APIBaseTest, ClickhouseTestMixin):
    def _create_sample_usage_data(self) -> None:
        """
        For this test, we create a lot of data around the current date 2022-01-01
        so that we can test the report overall
        """
        self.org_internal = Organization.objects.create(name="Internal metrics org", for_internal_metrics=True)
        self.org_1 = self.organization
        self.org_2 = Organization.objects.create(name="Org 2")
        self.org_internal_team_0 = Team.objects.create(organization=self.org_internal, name="Team 0 org internal")
        self.org_1_team_1 = self.team  # self.organization already has a team
        self.org_1_team_2 = Team.objects.create(organization=self.org_1, name="Team 2 org 1")
        self.org_2_team_3 = Team.objects.create(organization=self.org_2, name="Team 3 org 2")

        with self.settings(USE_TZ=False):

            # Events for internal org
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_internal_team_0)

            for i in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_internal_team_0,
                )

            # Events for org 1 team 1
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_1_team_1)

            for i in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_1,
                )

            # Events before the period
            for i in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$out-of-range",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(hours=48),
                    team=self.org_1_team_1,
                )

            # Events after the period
            for i in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$out-of-range",
                    properties={"$lib": "$mobile"},
                    timestamp=now() + relativedelta(hours=48),
                    team=self.org_1_team_1,
                )

            # Events for org 1 team 2
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_1_team_2)

            for i in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_2,
                )

            # Events for org 2 team 3
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_2_team_3)

            for i in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_2_team_3,
                )

            flush_persons_and_events()

    def _select_report_by_org_id(self, org_id: str, reports: List[Dict]) -> Dict:
        return [report for report in reports if report["organization_id"] == org_id][0]

    def _create_plugin(self, name: str, enabled: bool) -> None:
        plugin = Plugin.objects.create(organization_id=self.team.organization.pk, name=name)
        PluginConfig.objects.create(plugin=plugin, enabled=enabled, order=1)

    @patch("os.environ", {"DEPLOYMENT": "tests"})
    def test_usage_report(self) -> None:

        with self.settings(SITE_URL="http://test.posthog.com"):
            self._create_sample_usage_data()
            all_reports = send_all_org_usage_reports(dry_run=True)

            report = all_reports[0]
            assert report["table_sizes"]
            assert report["table_sizes"]["posthog_event"] < 10**7  # <10MB
            assert report["table_sizes"]["posthog_sessionrecordingevent"] < 10**7  # <10MB

            assert len(all_reports) == 2

            expectation = [
                {
                    "posthog_version": all_reports[0]["posthog_version"],
                    "deployment_infrastructure": "tests",
                    "realm": "hosted-clickhouse",
                    "period": {
                        "start_inclusive": "2022-01-09T00:00:00+00:00",
                        "end_inclusive": "2022-01-09T23:59:59.999999+00:00",
                    },
                    "site_url": "http://test.posthog.com",
                    "product": "open source",
                    "helm": {},
                    "clickhouse_version": all_reports[0]["clickhouse_version"],
                    "users_who_logged_in": [],
                    "users_who_logged_in_count": 0,
                    "users_who_signed_up": [],
                    "users_who_signed_up_count": 0,
                    "table_sizes": all_reports[0]["table_sizes"],
                    "plugins_installed": {},
                    "plugins_enabled": {},
                    "event_count_lifetime": 40,
                    "event_count_in_period": 20,
                    "event_count_in_month": 30,
                    "event_count_with_groups_in_period": 0,
                    "recording_count_in_period": 0,
                    "recording_count_total": 0,
                    "group_types_total": 0,
                    "dashboard_count": 0,
                    "dashboard_template_count": 0,
                    "dashboard_shared_count": 0,
                    "dashboard_tagged_count": 0,
                    "ff_count": 0,
                    "ff_active_count": 0,
                    "date": "2022-01-09",
                    "organization_id": str(self.organization.id),
                    "organization_name": "Test",
                    "organization_created_at": "2022-01-10T00:01:00+00:00",
                    "organization_user_count": 1,
                    "team_count": 1,
                    "teams": {
                        self.org_1_team_1.id: {
                            "event_count_lifetime": 20,
                            "event_count_in_period": 10,
                            "event_count_in_month": 30,
                            "event_count_with_groups_in_period": 0,
                            "recording_count_in_period": 0,
                            "recording_count_total": 0,
                            "group_types_total": 0,
                            "dashboard_count": 0,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 0,
                            "dashboard_tagged_count": 0,
                            "ff_count": 0,
                            "ff_active_count": 0,
                        },
                        self.org_1_team_2.id: {
                            "event_count_lifetime": 10,
                            "event_count_in_period": 10,
                            "event_count_in_month": 10,
                            "event_count_with_groups_in_period": 0,
                            "recording_count_in_period": 0,
                            "recording_count_total": 0,
                            "group_types_total": 0,
                            "dashboard_count": 0,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 0,
                            "dashboard_tagged_count": 0,
                            "ff_count": 0,
                            "ff_active_count": 0,
                        },
                    },
                },
                {
                    "posthog_version": all_reports[1]["posthog_version"],
                    "deployment_infrastructure": "tests",
                    "realm": "hosted-clickhouse",
                    "period": {
                        "start_inclusive": "2022-01-09T00:00:00+00:00",
                        "end_inclusive": "2022-01-09T23:59:59.999999+00:00",
                    },
                    "site_url": "http://test.posthog.com",
                    "product": "open source",
                    "helm": {},
                    "clickhouse_version": all_reports[1]["clickhouse_version"],
                    "users_who_logged_in": [],
                    "users_who_logged_in_count": 0,
                    "users_who_signed_up": [],
                    "users_who_signed_up_count": 0,
                    "table_sizes": all_reports[1]["table_sizes"],
                    "plugins_installed": {},
                    "plugins_enabled": {},
                    "event_count_lifetime": 10,
                    "event_count_in_period": 10,
                    "event_count_in_month": 10,
                    "event_count_with_groups_in_period": 0,
                    "recording_count_in_period": 0,
                    "recording_count_total": 0,
                    "group_types_total": 0,
                    "dashboard_count": 0,
                    "dashboard_template_count": 0,
                    "dashboard_shared_count": 0,
                    "dashboard_tagged_count": 0,
                    "ff_count": 0,
                    "ff_active_count": 0,
                    "date": "2022-01-09",
                    "organization_id": str(self.org_2.id),
                    "organization_name": "Org 2",
                    "organization_created_at": "2022-01-10T00:01:00+00:00",
                    "organization_user_count": 0,
                    "team_count": 1,
                    "teams": {
                        self.org_2_team_3.id: {
                            "event_count_lifetime": 10,
                            "event_count_in_period": 10,
                            "event_count_in_month": 10,
                            "event_count_with_groups_in_period": 0,
                            "recording_count_in_period": 0,
                            "recording_count_total": 0,
                            "group_types_total": 0,
                            "dashboard_count": 0,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 0,
                            "dashboard_tagged_count": 0,
                            "ff_count": 0,
                            "ff_active_count": 0,
                        }
                    },
                },
            ]

            assert expectation == all_reports


#     def test_groups_usage(self) -> None:
#         GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
#         GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)
#         create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
#         create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})

#         with freeze_time("2021-11-11 00:30:00"):
#             _create_event(
#                 event="event",
#                 lib="web",
#                 distinct_id="user_1",
#                 team=self.team,
#                 timestamp="2021-11-10 02:00:00",
#                 properties={"$group_0": "org:5"},
#             )
#             _create_event(
#                 event="event",
#                 lib="web",
#                 distinct_id="user_1",
#                 team=self.team,
#                 timestamp="2021-11-10 05:00:00",
#                 properties={"$group_0": "org:6"},
#             )

#             _create_event(
#                 event="event", lib="web", distinct_id="user_7", team=self.team, timestamp="2021-11-10 10:00:00"
#             )

#             all_reports = send_all_org_usage_reports(dry_run=True)
#             org_report = self._select_report_by_org_id(str(self.organization.id), all_reports)

#             team_id = list(org_report["teams"].keys())[0]
#             self.assertEqual(org_report["teams"][team_id]["group_types_total"], 2)
#             self.assertEqual(org_report["event_count_in_period"], 3)
#             self.assertEqual(org_report["event_count_with_groups_in_period"], 2)

#     def test_recording_usage(self) -> None:
#         default_team = self._create_new_org_and_team()
#         with freeze_time("2021-11-11 00:30:00"):

#             create_snapshot(
#                 has_full_snapshot=False,
#                 distinct_id="user",
#                 session_id="1",
#                 timestamp=now() - relativedelta(days=0, hours=2),
#                 team_id=default_team.id,
#             )
#             create_snapshot(
#                 has_full_snapshot=False,
#                 distinct_id="user",
#                 session_id="1",
#                 timestamp=now() - relativedelta(days=0, hours=2),
#                 team_id=default_team.id,
#             )
#             create_snapshot(
#                 has_full_snapshot=False,
#                 distinct_id="user2",
#                 session_id="2",
#                 timestamp=now() - relativedelta(days=0, hours=2),
#                 team_id=default_team.id,
#             )
#             create_snapshot(
#                 has_full_snapshot=False,
#                 distinct_id="user",
#                 session_id="1",
#                 timestamp=now() - relativedelta(days=0, hours=2),
#                 team_id=default_team.id,
#             )
#             all_reports = send_all_org_usage_reports(dry_run=True)
#             org_report = self._select_report_by_org_id(str(default_team.organization.id), all_reports)

#             self.assertEqual(org_report["recording_count_in_period"], 2)

#             create_snapshot(
#                 has_full_snapshot=False,
#                 distinct_id="user2",
#                 session_id="3",
#                 timestamp=now(),
#                 team_id=default_team.id,
#             )
#             create_snapshot(
#                 has_full_snapshot=False,
#                 distinct_id="user",
#                 session_id="4",
#                 timestamp=now(),
#                 team_id=default_team.id,
#             )
#             # Check recording usage in current period is unchanged
#             updated_org_reports = send_all_org_usage_reports(dry_run=True)
#             updated_org_report = self._select_report_by_org_id(str(default_team.organization.id), updated_org_reports)

#             self.assertEqual(
#                 updated_org_report["recording_count_in_period"],
#                 org_report["recording_count_in_period"],
#             )

#     def test_status_report_plugins(self) -> None:
#         self._create_plugin("Installed but not enabled", False)
#         self._create_plugin("Installed and enabled", True)
#         all_reports = send_all_org_usage_reports(dry_run=True)
#         org_report = self._select_report_by_org_id(str(self.organization.id), all_reports)

#         self.assertEqual(
#             org_report["plugins_installed"],
#             {"Installed but not enabled": 1, "Installed and enabled": 1},
#         )
#         self.assertEqual(org_report["plugins_enabled"], {"Installed and enabled": 1})

#     def test_status_report_duplicate_distinct_ids(self) -> None:
#         create_person_distinct_id(self.team.id, "duplicate_id1", str(UUIDT()))
#         create_person_distinct_id(self.team.id, "duplicate_id1", str(UUIDT()))
#         create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))
#         create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))
#         create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))

#         for index in range(0, 2):
#             sync_execute(
#                 "INSERT INTO person_distinct_id SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, 1, %(timestamp)s, 0 VALUES",
#                 {
#                     "distinct_id": "duplicate_id_old",
#                     "person_id": str(UUIDT()),
#                     "team_id": self.team.id,
#                     "timestamp": "2020-01-01 12:01:0%s" % index,
#                 },
#             )

#         all_reports = send_all_org_usage_reports(dry_run=True)
#         report = all_reports[0]
#         team_id = list(report["teams"].keys())[0]
#         team_report = report["teams"][team_id]

#         duplicate_ids_report = team_report["duplicate_distinct_ids"]

#         expected_result = {
#             "prev_total_ids_with_duplicates": 1,
#             "prev_total_extra_distinct_id_rows": 1,
#             "new_total_ids_with_duplicates": 2,
#             "new_total_extra_distinct_id_rows": 4,
#         }

#         self.assertEqual(duplicate_ids_report, expected_result)

#     # CH only
#     def test_status_report_multiple_ids_per_person(self) -> None:
#         person_id1 = str(UUIDT())
#         person_id2 = str(UUIDT())

#         create_person_distinct_id(self.team.id, "id1", person_id1)
#         create_person_distinct_id(self.team.id, "id2", person_id1)
#         create_person_distinct_id(self.team.id, "id3", person_id1)
#         create_person_distinct_id(self.team.id, "id4", person_id1)
#         create_person_distinct_id(self.team.id, "id5", person_id1)

#         create_person_distinct_id(self.team.id, "id6", person_id2)
#         create_person_distinct_id(self.team.id, "id7", person_id2)
#         create_person_distinct_id(self.team.id, "id8", person_id2)

#         all_reports = send_all_org_usage_reports(dry_run=True)
#         report = all_reports[0]
#         team_id = list(report["teams"].keys())[0]
#         team_report = report["teams"][team_id]

#         multiple_ids_report = team_report["multiple_ids_per_person"]

#         expected_result = {"total_persons_with_more_than_2_ids": 2, "max_distinct_ids_for_one_person": 5}

#         self.assertEqual(multiple_ids_report, expected_result)


# class SendUsageTest(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
#     def setUp(self) -> None:
#         super().setUp()

#         self.team2 = Team.objects.create(organization=self.organization)

#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-08T14:01:01Z")
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T12:01:01Z")
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T13:01:01Z")
#         _create_event(
#             event="$$internal_metrics_shouldnt_be_billed",
#             team=self.team,
#             distinct_id=1,
#             timestamp="2021-10-09T13:01:01Z",
#         )
#         _create_event(event="$pageview", team=self.team2, distinct_id=1, timestamp="2021-10-09T14:01:01Z")
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-10T14:01:01Z")
#         flush_persons_and_events()

#     @freeze_time("2021-10-10T23:01:00Z")
#     @patch("posthog.tasks.usage_report.Client")
#     @patch("requests.post")
#     def test_send_usage(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
#         mockresponse = Mock()
#         mock_post.return_value = mockresponse
#         mockresponse.status_code = 200
#         mockresponse.json = lambda: {"ok": True}
#         mock_posthog = MagicMock()
#         mock_client.return_value = mock_posthog

#         all_reports = send_all_org_usage_reports(dry_run=False)
#         license = License.objects.first()
#         assert license
#         token = build_billing_token(license, self.organization)
#         mock_post.assert_called_once_with(
#             f"{BILLING_SERVICE_URL}/api/usage", json=all_reports[0], headers={"Authorization": f"Bearer {token}"}
#         )

#         mock_posthog.capture.assert_any_call(
#             get_machine_id(),
#             "organization usage report",
#             {**all_reports[0], "scope": "machine"},
#             groups={"instance": ANY},
#             timestamp=None,
#         )

#     @freeze_time("2021-10-10T23:01:00Z")
#     @patch("posthog.tasks.usage_report.Client")
#     @patch("requests.post")
#     def test_send_usage_cloud(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
#         with self.is_cloud(True):
#             mockresponse = Mock()
#             mock_post.return_value = mockresponse
#             mockresponse.status_code = 200
#             mockresponse.json = lambda: {"ok": True}
#             mock_posthog = MagicMock()
#             mock_client.return_value = mock_posthog

#             all_reports = send_all_org_usage_reports(dry_run=False)
#             license = License.objects.first()
#             assert license
#             token = build_billing_token(license, self.organization)
#             mock_post.assert_called_once_with(
#                 f"{BILLING_SERVICE_URL}/api/usage", json=all_reports[0], headers={"Authorization": f"Bearer {token}"}
#             )

#             mock_posthog.capture.assert_any_call(
#                 self.user.distinct_id,
#                 "organization usage report",
#                 {**all_reports[0], "scope": "user"},
#                 groups={"instance": "http://localhost:8000", "organization": str(self.organization.id)},
#                 timestamp=None,
#             )

#     @freeze_time("2021-10-10T23:01:00Z")
#     @patch("posthog.tasks.usage_report.Client")
#     @patch("requests.post")
#     def test_send_usage_billing_service_not_reachable(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
#         mockresponse = Mock()
#         mock_post.return_value = mockresponse
#         mockresponse.status_code = 404
#         mockresponse.ok = False
#         mockresponse.json = lambda: {"code": "not_found"}
#         mockresponse.content = ""

#         mock_posthog = MagicMock()
#         mock_client.return_value = mock_posthog

#         send_all_org_usage_reports(dry_run=False)
#         mock_posthog.capture.assert_any_call(
#             get_machine_id(),
#             "billing service usage report failure",
#             {"code": 404, "scope": "machine"},
#             groups={"instance": ANY},
#             timestamp=None,
#         )

#     @freeze_time("2021-10-10T23:01:00Z")
#     @patch("posthog.tasks.usage_report.get_org_usage_report")
#     @patch("posthog.tasks.usage_report.Client")
#     @patch("requests.post")
#     def test_send_usage_backup(
#         self, mock_post: MagicMock, mock_client: MagicMock, mock_get_org_usage_report: MagicMock
#     ) -> None:
#         mockresponse = Mock()
#         mock_post.return_value = mockresponse
#         mockresponse.status_code = 200
#         mockresponse.json = lambda: {"ok": True}
#         mock_get_org_usage_report.side_effect = Exception("something went wrong")

#         with pytest.raises(Exception):
#             send_all_org_usage_reports(dry_run=False)
#         license = License.objects.first()
#         assert license
#         token = build_billing_token(license, self.organization)
#         mock_post.assert_called_once_with(
#             f"{BILLING_SERVICE_URL}/api/usage",
#             json={
#                 "organization_id": str(self.organization.id),
#                 "date": "2021-10-09",
#                 "event_count_in_period": 4,
#                 "recording_count_in_period": 0,
#             },
#             headers={"Authorization": f"Bearer {token}"},
#         )


# class SendUsageNoLicenseTest(APIBaseTest):
#     @freeze_time("2021-10-10T23:01:00Z")
#     @patch("posthog.tasks.usage_report.Client")
#     @patch("requests.post")
#     def test_no_license(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
#         # Same test, we just don't include the LicensedTestMixin so no license
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-08T14:01:01Z")
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T12:01:01Z")
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T13:01:01Z")
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-09T14:01:01Z")
#         _create_event(event="$pageview", team=self.team, distinct_id=1, timestamp="2021-10-10T14:01:01Z")

#         flush_persons_and_events()

#         all_reports = send_all_org_usage_reports()

#         mock_post.assert_called_once_with(f"{BILLING_SERVICE_URL}/api/usage", json=all_reports[0], headers={})
