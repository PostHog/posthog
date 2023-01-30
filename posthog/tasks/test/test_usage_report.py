from typing import Dict, List
from unittest.mock import ANY, MagicMock, Mock, call, patch
from uuid import uuid4

import structlog
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from ee.api.billing import build_billing_token
from ee.api.test.base import LicensedTestMixin
from ee.models.license import License
from ee.settings import BILLING_SERVICE_URL
from posthog.models import Organization, Plugin, Team
from posthog.models.dashboard import Dashboard
from posthog.models.feature_flag import FeatureFlag
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.plugin import PluginConfig
from posthog.models.sharing_configuration import SharingConfiguration
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
from posthog.utils import get_machine_id

logger = structlog.get_logger(__name__)


@freeze_time("2022-01-10T00:01:00Z")
class UsageReport(APIBaseTest, ClickhouseTestMixin, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        self.expected_properties: dict = {}

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

            for _ in range(0, 10):
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

            Dashboard.objects.create(team=self.org_1_team_1, name="Dash one", created_by=self.user)

            dashboard = Dashboard.objects.create(
                team=self.org_1_team_1,
                name="Dash public",
                created_by=self.user,
            )
            SharingConfiguration.objects.create(
                team=self.org_1_team_1, dashboard=dashboard, access_token="testtoken", enabled=True
            )

            FeatureFlag.objects.create(
                team=self.org_1_team_1,
                rollout_percentage=30,
                name="Disabled",
                key="disabled-flag",
                created_by=self.user,
                active=False,
            )

            FeatureFlag.objects.create(
                team=self.org_1_team_1,
                rollout_percentage=30,
                name="Enabled",
                key="enabled-flag",
                created_by=self.user,
                active=True,
            )

            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_1,
                )

            # Events before the period
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$out-of-range",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(hours=48),
                    team=self.org_1_team_1,
                )

            # Events after the period
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$out-of-range",
                    properties={"$lib": "$mobile"},
                    timestamp=now() + relativedelta(hours=48),
                    team=self.org_1_team_1,
                )

            # Some groups
            GroupTypeMapping.objects.create(team=self.org_1_team_1, group_type="organization", group_type_index=0)
            GroupTypeMapping.objects.create(team=self.org_1_team_1, group_type="company", group_type_index=1)
            create_group(
                team_id=self.org_1_team_1.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"}
            )
            create_group(
                team_id=self.org_1_team_1.pk,
                group_type_index=0,
                group_key="org:6",
                properties={"industry": "technology"},
            )

            _create_event(
                event="event",
                lib="web",
                distinct_id=distinct_id,
                team=self.team,
                timestamp=now() - relativedelta(hours=12),
                properties={"$group_0": "org:5"},
            )
            _create_event(
                event="event",
                lib="web",
                distinct_id=distinct_id,
                team=self.team,
                timestamp=now() - relativedelta(hours=12),
                properties={"$group_0": "org:6"},
            )

            # Events for org 1 team 2
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_1_team_2)

            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_2,
                )

            # recordings in period  - 5 sessions with 5 snapshots each
            for i in range(0, 5):
                for _ in range(0, 5):
                    create_snapshot(
                        has_full_snapshot=True,
                        distinct_id=distinct_id,
                        session_id=i,
                        timestamp=now() - relativedelta(hours=12),
                        team_id=self.org_1_team_2.id,
                    )

            # recordings out of period  - 5 sessions with 5 snapshots each
            for i in range(0, 10):
                for _ in range(0, 5):
                    create_snapshot(
                        has_full_snapshot=True,
                        distinct_id=distinct_id,
                        session_id=i + 10,
                        timestamp=now() - relativedelta(hours=48),
                        team_id=self.org_1_team_2.id,
                    )

            # Events for org 2 team 3
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_2_team_3)

            for _ in range(0, 10):
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

    def _test_usage_report(self) -> List[dict]:

        with self.settings(SITE_URL="http://test.posthog.com"):
            self._create_sample_usage_data()
            self._create_plugin("Installed but not enabled", False)
            self._create_plugin("Installed and enabled", True)

            all_reports = send_all_org_usage_reports(dry_run=False)

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
                    "plugins_installed": {"Installed and enabled": 1, "Installed but not enabled": 1},
                    "plugins_enabled": {"Installed and enabled": 1},
                    "instance_tag": "none",
                    "event_count_lifetime": 42,
                    "event_count_in_period": 22,
                    "event_count_in_month": 32,
                    "event_count_with_groups_in_period": 2,
                    "recording_count_in_period": 5,
                    "recording_count_total": 15,
                    "group_types_total": 2,
                    "dashboard_count": 2,
                    "dashboard_template_count": 0,
                    "dashboard_shared_count": 1,
                    "dashboard_tagged_count": 0,
                    "ff_count": 2,
                    "ff_active_count": 1,
                    "date": "2022-01-09",
                    "organization_id": str(self.organization.id),
                    "organization_name": "Test",
                    "organization_created_at": "2022-01-10T00:01:00+00:00",
                    "organization_user_count": 1,
                    "team_count": 2,
                    "teams": {
                        self.org_1_team_1.id: {
                            "event_count_lifetime": 32,
                            "event_count_in_period": 12,
                            "event_count_in_month": 22,
                            "event_count_with_groups_in_period": 2,
                            "recording_count_in_period": 0,
                            "recording_count_total": 0,
                            "group_types_total": 2,
                            "dashboard_count": 2,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 1,
                            "dashboard_tagged_count": 0,
                            "ff_count": 2,
                            "ff_active_count": 1,
                        },
                        self.org_1_team_2.id: {
                            "event_count_lifetime": 10,
                            "event_count_in_period": 10,
                            "event_count_in_month": 10,
                            "event_count_with_groups_in_period": 0,
                            "recording_count_in_period": 5,
                            "recording_count_total": 15,
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
                    "plugins_installed": {"Installed and enabled": 1, "Installed but not enabled": 1},
                    "plugins_enabled": {"Installed and enabled": 1},
                    "instance_tag": "none",
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

            for item in expectation:
                item.update(**self.expected_properties)

            # tricky: list could be in different order
            assert len(all_reports) == 2
            for report in all_reports:
                if report["organization_id"] == expectation[0]["organization_id"]:
                    assert report == expectation[0]
                elif report["organization_id"] == expectation[1]["organization_id"]:
                    assert report == expectation[1]

            return all_reports

    @patch("os.environ", {"DEPLOYMENT": "tests"})
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_unlicensed_usage_report(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        self.expected_properties = {}
        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.status_code = 200
        mockresponse.json = lambda: {}
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        all_reports = self._test_usage_report()

        # Check calls to other services
        mock_post.assert_not_called()

        calls = [
            call(
                get_machine_id(),
                "organization usage report",
                {**all_reports[0], "scope": "machine"},
                groups={"instance": ANY},
                timestamp=None,
            ),
            call(
                get_machine_id(),
                "organization usage report",
                {**all_reports[1], "scope": "machine"},
                groups={"instance": ANY},
                timestamp=None,
            ),
        ]

        mock_posthog.capture.assert_has_calls(calls, any_order=True)


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
        mockresponse.json = lambda: {}
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        all_reports = send_all_org_usage_reports(dry_run=False)
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
            mockresponse.json = lambda: {}
            mock_posthog = MagicMock()
            mock_client.return_value = mock_posthog

            all_reports = send_all_org_usage_reports(dry_run=False)
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

        send_all_org_usage_reports(dry_run=False)
        mock_posthog.capture.assert_any_call(
            get_machine_id(),
            "organization usage report to billing service failure",
            {"err": ANY, "scope": "machine"},
            groups={"instance": ANY},
            timestamp=None,
        )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_org_usage_updated_correctly(self, mock_post: MagicMock, mock_client: MagicMock) -> None:

        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.status_code = 200
        usage = {
            "events": {"usage": 10000, "limit": None},
            "recordings": {
                "usage": 1000,
                "limit": None,
            },
        }
        mockresponse.json = lambda: {"organization_usage": usage}
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        send_all_org_usage_reports(dry_run=False)

        self.team.organization.refresh_from_db()
        assert self.team.organization.usage == usage


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

        send_all_org_usage_reports()

        mock_post.assert_not_called()
