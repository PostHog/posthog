from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import ANY, MagicMock, Mock, call, patch
from uuid import uuid4

import pytest
import structlog
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc
from django.test import TestCase
from django.utils.timezone import now
from freezegun import freeze_time

from ee.api.test.base import LicensedTestMixin
from ee.billing.billing_manager import build_billing_token
from ee.models.license import License
from ee.settings import BILLING_SERVICE_URL
from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models import Organization, Plugin, Team
from posthog.models.dashboard import Dashboard
from posthog.models.event.util import create_event
from posthog.models.feature_flag import FeatureFlag
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.plugin import PluginConfig
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.schema import EventsQuery
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.tasks.usage_report import (
    _get_all_org_reports,
    _get_all_usage_data_as_team_rows,
    _get_full_org_usage_report,
    _get_full_org_usage_report_as_dict,
    _get_team_report,
    capture_event,
    get_instance_metadata,
    send_all_org_usage_reports,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseDestroyTablesMixin,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from posthog.utils import get_machine_id, get_previous_day

logger = structlog.get_logger(__name__)


@freeze_time("2022-01-10T00:01:00Z")
class UsageReport(APIBaseTest, ClickhouseTestMixin, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        # make sure we don't collapse duplicate rows
        sync_execute("SYSTEM STOP MERGES")

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

            _create_event(
                distinct_id=distinct_id,
                event="survey sent",
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
            )

            Dashboard.objects.create(team=self.org_1_team_1, name="Dash one", created_by=self.user)

            dashboard = Dashboard.objects.create(
                team=self.org_1_team_1,
                name="Dash public",
                created_by=self.user,
            )
            SharingConfiguration.objects.create(
                team=self.org_1_team_1,
                dashboard=dashboard,
                access_token="testtoken",
                enabled=True,
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

            uuids = [uuid4() for _ in range(0, 10)]
            for uuid in uuids:
                create_event(
                    event_uuid=uuid,
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_1,
                )

            # create duplicate events
            for uuid in uuids:
                _create_event(
                    event_uuid=uuid,
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_1,
                )

            _create_event(
                distinct_id=distinct_id,
                event="$feature_flag_called",
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
                team_id=self.org_1_team_1.pk,
                group_type_index=0,
                group_key="org:5",
                properties={"industry": "finance"},
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
            for i in range(1, 6):
                for _ in range(0, 5):
                    session_id = str(i)
                    timestamp = now() - relativedelta(hours=12)
                    produce_replay_summary(
                        team_id=self.org_1_team_2.id,
                        session_id=session_id,
                        distinct_id=distinct_id,
                        first_timestamp=timestamp,
                        last_timestamp=timestamp,
                    )

            # recordings out of period  - 5 sessions with 5 snapshots each
            for i in range(1, 11):
                for _ in range(0, 5):
                    id1 = str(i + 10)
                    timestamp1 = now() - relativedelta(hours=48)
                    produce_replay_summary(
                        team_id=self.org_1_team_2.id,
                        session_id=id1,
                        distinct_id=distinct_id,
                        first_timestamp=timestamp1,
                        last_timestamp=timestamp1,
                    )

            # ensure there is a recording that starts before the period and ends during the period
            # report is going to be for "yesterday" relative to the test so...
            start_of_day = datetime.combine(now().date(), datetime.min.time()) - relativedelta(days=1)
            session_that_will_not_match = "session-that-will-not-match-because-it-starts-before-the-period"
            timestamp2 = start_of_day - relativedelta(hours=1)
            produce_replay_summary(
                team_id=self.org_1_team_2.id,
                session_id=session_that_will_not_match,
                distinct_id=distinct_id,
                first_timestamp=timestamp2,
                last_timestamp=timestamp2,
            )
            produce_replay_summary(
                team_id=self.org_1_team_2.id,
                session_id=session_that_will_not_match,
                distinct_id=distinct_id,
                first_timestamp=start_of_day,
                last_timestamp=start_of_day,
            )
            timestamp3 = start_of_day + relativedelta(hours=1)
            produce_replay_summary(
                team_id=self.org_1_team_2.id,
                session_id=session_that_will_not_match,
                distinct_id=distinct_id,
                first_timestamp=timestamp3,
                last_timestamp=timestamp3,
            )
            _create_event(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                properties={"$lib": "$web"},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_2,
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
            _create_event(
                distinct_id=distinct_id,
                event="$feature_flag_called",
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

            period = get_previous_day()
            period_start, period_end = period
            all_reports = _get_all_org_reports(period_start, period_end)
            report = _get_full_org_usage_report_as_dict(
                _get_full_org_usage_report(
                    all_reports[str(self.organization.id)],
                    get_instance_metadata(period),
                )
            )

            assert report["table_sizes"]
            assert report["table_sizes"]["posthog_event"] < 10**7  # <10MB
            assert report["table_sizes"]["posthog_sessionrecordingevent"] < 10**7  # <10MB

            assert len(all_reports) == 2

            expectations = [
                {
                    "deployment_infrastructure": "tests",
                    "realm": "hosted-clickhouse",
                    "period": {
                        "start_inclusive": "2022-01-09T00:00:00+00:00",
                        "end_inclusive": "2022-01-09T23:59:59.999999+00:00",
                    },
                    "site_url": "http://test.posthog.com",
                    "product": "open source",
                    "helm": {},
                    "clickhouse_version": report["clickhouse_version"],
                    "users_who_logged_in": [],
                    "users_who_logged_in_count": 0,
                    "users_who_signed_up": [],
                    "users_who_signed_up_count": 0,
                    "table_sizes": report["table_sizes"],
                    "plugins_installed": {
                        "Installed and enabled": 1,
                        "Installed but not enabled": 1,
                    },
                    "plugins_enabled": {"Installed and enabled": 1},
                    "instance_tag": "none",
                    "event_count_lifetime": 55,
                    "event_count_in_period": 23,
                    "event_count_in_month": 43,
                    "event_count_with_groups_in_period": 2,
                    "recording_count_in_period": 5,
                    "recording_count_total": 16,
                    "group_types_total": 2,
                    "dashboard_count": 2,
                    "dashboard_template_count": 0,
                    "dashboard_shared_count": 1,
                    "dashboard_tagged_count": 0,
                    "ff_count": 2,
                    "ff_active_count": 1,
                    "decide_requests_count_in_month": 0,
                    "decide_requests_count_in_period": 0,
                    "local_evaluation_requests_count_in_month": 0,
                    "local_evaluation_requests_count_in_period": 0,
                    "billable_feature_flag_requests_count_in_month": 0,
                    "billable_feature_flag_requests_count_in_period": 0,
                    "survey_responses_count_in_period": 1,
                    "survey_responses_count_in_month": 1,
                    "hogql_app_bytes_read": 0,
                    "hogql_app_rows_read": 0,
                    "hogql_app_duration_ms": 0,
                    "hogql_api_bytes_read": 0,
                    "hogql_api_rows_read": 0,
                    "hogql_api_duration_ms": 0,
                    "event_explorer_app_bytes_read": 0,
                    "event_explorer_app_rows_read": 0,
                    "event_explorer_app_duration_ms": 0,
                    "event_explorer_api_bytes_read": 0,
                    "event_explorer_api_rows_read": 0,
                    "event_explorer_api_duration_ms": 0,
                    "rows_synced_in_period": 0,
                    "date": "2022-01-09",
                    "organization_id": str(self.organization.id),
                    "organization_name": "Test",
                    "organization_created_at": "2022-01-10T00:01:00+00:00",
                    "organization_user_count": 1,
                    "team_count": 2,
                    "teams": {
                        str(self.org_1_team_1.id): {
                            "event_count_lifetime": 44,
                            "event_count_in_period": 13,
                            "event_count_in_month": 33,
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
                            "decide_requests_count_in_month": 0,
                            "decide_requests_count_in_period": 0,
                            "local_evaluation_requests_count_in_month": 0,
                            "local_evaluation_requests_count_in_period": 0,
                            "billable_feature_flag_requests_count_in_month": 0,
                            "billable_feature_flag_requests_count_in_period": 0,
                            "survey_responses_count_in_period": 1,
                            "survey_responses_count_in_month": 1,
                            "hogql_app_bytes_read": 0,
                            "hogql_app_rows_read": 0,
                            "hogql_app_duration_ms": 0,
                            "hogql_api_bytes_read": 0,
                            "hogql_api_rows_read": 0,
                            "hogql_api_duration_ms": 0,
                            "event_explorer_app_bytes_read": 0,
                            "event_explorer_app_rows_read": 0,
                            "event_explorer_app_duration_ms": 0,
                            "event_explorer_api_bytes_read": 0,
                            "event_explorer_api_rows_read": 0,
                            "event_explorer_api_duration_ms": 0,
                            "rows_synced_in_period": 0,
                        },
                        str(self.org_1_team_2.id): {
                            "event_count_lifetime": 11,
                            "event_count_in_period": 10,
                            "event_count_in_month": 10,
                            "event_count_with_groups_in_period": 0,
                            "recording_count_in_period": 5,
                            "recording_count_total": 16,
                            "group_types_total": 0,
                            "dashboard_count": 0,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 0,
                            "dashboard_tagged_count": 0,
                            "ff_count": 0,
                            "ff_active_count": 0,
                            "decide_requests_count_in_month": 0,
                            "decide_requests_count_in_period": 0,
                            "local_evaluation_requests_count_in_month": 0,
                            "local_evaluation_requests_count_in_period": 0,
                            "billable_feature_flag_requests_count_in_month": 0,
                            "billable_feature_flag_requests_count_in_period": 0,
                            "survey_responses_count_in_period": 0,
                            "survey_responses_count_in_month": 0,
                            "hogql_app_bytes_read": 0,
                            "hogql_app_rows_read": 0,
                            "hogql_app_duration_ms": 0,
                            "hogql_api_bytes_read": 0,
                            "hogql_api_rows_read": 0,
                            "hogql_api_duration_ms": 0,
                            "event_explorer_app_bytes_read": 0,
                            "event_explorer_app_rows_read": 0,
                            "event_explorer_app_duration_ms": 0,
                            "event_explorer_api_bytes_read": 0,
                            "event_explorer_api_rows_read": 0,
                            "event_explorer_api_duration_ms": 0,
                            "rows_synced_in_period": 0,
                        },
                    },
                },
                {
                    "deployment_infrastructure": "tests",
                    "realm": "hosted-clickhouse",
                    "period": {
                        "start_inclusive": "2022-01-09T00:00:00+00:00",
                        "end_inclusive": "2022-01-09T23:59:59.999999+00:00",
                    },
                    "site_url": "http://test.posthog.com",
                    "product": "open source",
                    "helm": {},
                    "clickhouse_version": report["clickhouse_version"],
                    "users_who_logged_in": [],
                    "users_who_logged_in_count": 0,
                    "users_who_signed_up": [],
                    "users_who_signed_up_count": 0,
                    "table_sizes": report["table_sizes"],
                    "plugins_installed": {
                        "Installed and enabled": 1,
                        "Installed but not enabled": 1,
                    },
                    "plugins_enabled": {"Installed and enabled": 1},
                    "instance_tag": "none",
                    "event_count_lifetime": 11,
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
                    "decide_requests_count_in_month": 0,
                    "decide_requests_count_in_period": 0,
                    "local_evaluation_requests_count_in_month": 0,
                    "local_evaluation_requests_count_in_period": 0,
                    "billable_feature_flag_requests_count_in_month": 0,
                    "billable_feature_flag_requests_count_in_period": 0,
                    "survey_responses_count_in_period": 0,
                    "survey_responses_count_in_month": 0,
                    "hogql_app_bytes_read": 0,
                    "hogql_app_rows_read": 0,
                    "hogql_app_duration_ms": 0,
                    "hogql_api_bytes_read": 0,
                    "hogql_api_rows_read": 0,
                    "hogql_api_duration_ms": 0,
                    "event_explorer_app_bytes_read": 0,
                    "event_explorer_app_rows_read": 0,
                    "event_explorer_app_duration_ms": 0,
                    "event_explorer_api_bytes_read": 0,
                    "event_explorer_api_rows_read": 0,
                    "event_explorer_api_duration_ms": 0,
                    "rows_synced_in_period": 0,
                    "date": "2022-01-09",
                    "organization_id": str(self.org_2.id),
                    "organization_name": "Org 2",
                    "organization_created_at": "2022-01-10T00:01:00+00:00",
                    "organization_user_count": 0,
                    "team_count": 1,
                    "teams": {
                        str(self.org_2_team_3.id): {
                            "event_count_lifetime": 11,
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
                            "decide_requests_count_in_month": 0,
                            "decide_requests_count_in_period": 0,
                            "local_evaluation_requests_count_in_month": 0,
                            "local_evaluation_requests_count_in_period": 0,
                            "billable_feature_flag_requests_count_in_month": 0,
                            "billable_feature_flag_requests_count_in_period": 0,
                            "survey_responses_count_in_period": 0,
                            "survey_responses_count_in_month": 0,
                            "hogql_app_bytes_read": 0,
                            "hogql_app_rows_read": 0,
                            "hogql_app_duration_ms": 0,
                            "hogql_api_bytes_read": 0,
                            "hogql_api_rows_read": 0,
                            "hogql_api_duration_ms": 0,
                            "event_explorer_app_bytes_read": 0,
                            "event_explorer_app_rows_read": 0,
                            "event_explorer_app_duration_ms": 0,
                            "event_explorer_api_bytes_read": 0,
                            "event_explorer_api_rows_read": 0,
                            "event_explorer_api_duration_ms": 0,
                            "rows_synced_in_period": 0,
                        }
                    },
                },
            ]

            for item in expectations:
                item.update(**self.expected_properties)

            # tricky: list could be in different order
            assert len(all_reports) == 2
            full_reports = []
            for expectation in expectations:
                report = _get_full_org_usage_report_as_dict(
                    _get_full_org_usage_report(
                        all_reports[expectation["organization_id"]],
                        get_instance_metadata(period),
                    )
                )
                assert report == expectation
                full_reports.append(report)

            return full_reports

    @freeze_time("2022-01-10T00:01:00Z")
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
        with self.settings(SITE_URL="http://test.posthog.com"):
            send_all_org_usage_reports()

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

        assert mock_posthog.capture.call_count == 2
        mock_posthog.capture.assert_has_calls(calls, any_order=True)


class HogQLUsageReport(APIBaseTest, ClickhouseTestMixin, ClickhouseDestroyTablesMixin):
    def test_usage_report_hogql_queries(self) -> None:
        for _ in range(0, 100):
            _create_event(
                distinct_id="hello",
                event="$event1",
                properties={"$lib": "$web"},
                timestamp=now() - relativedelta(hours=12),
                team=self.team,
            )
        flush_persons_and_events()
        sync_execute("SYSTEM FLUSH LOGS")
        sync_execute("TRUNCATE TABLE system.query_log")

        execute_hogql_query(
            query="select * from events limit 200",
            team=self.team,
            query_type="HogQLQuery",
        )
        EventsQueryRunner(query=EventsQuery(select=["event"], limit=50), team=self.team).calculate()
        sync_execute("SYSTEM FLUSH LOGS")

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_usage_data_as_team_rows(period_start, period_end)

        report = _get_team_report(all_reports, self.team)

        # We selected 200 or 50 rows, but still read 100 rows to return the query
        assert report.hogql_app_rows_read == 100
        assert report.hogql_app_bytes_read > 0
        assert report.event_explorer_app_rows_read == 100
        assert report.event_explorer_app_bytes_read > 0

        # Nothing was read via the API
        assert report.hogql_api_rows_read == 0
        assert report.event_explorer_api_rows_read == 0


@freeze_time("2022-01-10T00:01:00Z")
class TestFeatureFlagsUsageReport(ClickhouseDestroyTablesMixin, TestCase, ClickhouseTestMixin):
    def setUp(self) -> None:
        Team.objects.all().delete()
        return super().setUp()

    def _setup_teams(self) -> None:
        self.analytics_org = Organization.objects.create(name="PostHog")
        self.org_1 = Organization.objects.create(name="Org 1")
        self.org_2 = Organization.objects.create(name="Org 2")

        self.analytics_team = Team.objects.create(pk=2, organization=self.analytics_org, name="Analytics")

        self.org_1_team_1 = Team.objects.create(pk=3, organization=self.org_1, name="Team 1 org 1")
        self.org_1_team_2 = Team.objects.create(pk=4, organization=self.org_1, name="Team 2 org 1")
        self.org_2_team_3 = Team.objects.create(pk=5, organization=self.org_2, name="Team 3 org 2")

    @snapshot_clickhouse_queries
    @patch("posthog.tasks.usage_report.Client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_usage_report_decide_requests(self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock) -> None:
        self._setup_teams()
        for i in range(10):
            _create_event(
                distinct_id="3",
                event="decide usage",
                properties={"count": 10, "token": "correct"},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        for i in range(5):
            _create_event(
                distinct_id="4",
                event="decide usage",
                properties={"count": 1, "token": "correct"},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )
            _create_event(
                distinct_id="4",
                event="decide usage",
                properties={"count": 100, "token": "wrong"},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        for i in range(7):
            _create_event(
                distinct_id="5",
                event="decide usage",
                properties={"count": 100},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        # some out of range events
        _create_event(
            distinct_id="3",
            event="decide usage",
            properties={"count": 20000, "token": "correct"},
            timestamp=now() - relativedelta(days=20),
            team=self.analytics_team,
        )
        flush_persons_and_events()

        with self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="correct"):
            period = get_previous_day(at=now() + relativedelta(days=1))
            period_start, period_end = period
            all_reports = _get_all_org_reports(period_start, period_end)

        assert len(all_reports) == 3

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )
        assert org_1_report["organization_name"] == "Org 1"
        org_2_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_2.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["decide_requests_count_in_period"] == 11
        assert org_1_report["decide_requests_count_in_month"] == 105
        assert org_1_report["billable_feature_flag_requests_count_in_period"] == 11
        assert org_1_report["billable_feature_flag_requests_count_in_month"] == 105
        assert org_1_report["teams"]["3"]["decide_requests_count_in_period"] == 10
        assert org_1_report["teams"]["3"]["decide_requests_count_in_month"] == 100
        assert org_1_report["teams"]["3"]["billable_feature_flag_requests_count_in_period"] == 10
        assert org_1_report["teams"]["3"]["billable_feature_flag_requests_count_in_month"] == 100
        assert org_1_report["teams"]["4"]["decide_requests_count_in_period"] == 1
        assert org_1_report["teams"]["4"]["decide_requests_count_in_month"] == 5
        assert org_1_report["teams"]["4"]["billable_feature_flag_requests_count_in_period"] == 1
        assert org_1_report["teams"]["4"]["billable_feature_flag_requests_count_in_month"] == 5

        # because of wrong token, Org 2 has no decide counts.
        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["decide_requests_count_in_period"] == 0
        assert org_2_report["decide_requests_count_in_month"] == 0
        assert org_2_report["billable_feature_flag_requests_count_in_month"] == 0
        assert org_2_report["billable_feature_flag_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["decide_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["decide_requests_count_in_month"] == 0
        assert org_2_report["teams"]["5"]["billable_feature_flag_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["billable_feature_flag_requests_count_in_month"] == 0

    @patch("posthog.tasks.usage_report.Client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_usage_report_local_evaluation_requests(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()
        for i in range(10):
            _create_event(
                distinct_id="3",
                event="local evaluation usage",
                properties={"count": 10, "token": "correct"},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        for i in range(5):
            _create_event(
                distinct_id="4",
                event="local evaluation usage",
                properties={"count": 1, "token": "correct"},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )
            _create_event(
                distinct_id="4",
                event="local evaluation usage",
                properties={"count": 100, "token": "wrong"},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        for i in range(7):
            _create_event(
                distinct_id="5",
                event="local evaluation usage",
                properties={"count": 100},
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        # some out of range events
        _create_event(
            distinct_id="3",
            event="local evaluation usage",
            properties={"count": 20000, "token": "correct"},
            timestamp=now() - relativedelta(days=20),
            team=self.analytics_team,
        )
        flush_persons_and_events()

        with self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="correct"):
            period = get_previous_day(at=now() + relativedelta(days=1))
            period_start, period_end = period
            all_reports = _get_all_org_reports(period_start, period_end)

        assert len(all_reports) == 3

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )
        assert org_1_report["organization_name"] == "Org 1"
        org_2_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_2.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["local_evaluation_requests_count_in_period"] == 11
        assert org_1_report["local_evaluation_requests_count_in_month"] == 105
        assert org_1_report["decide_requests_count_in_period"] == 0
        assert org_1_report["decide_requests_count_in_month"] == 0
        assert org_1_report["billable_feature_flag_requests_count_in_period"] == 110
        assert org_1_report["billable_feature_flag_requests_count_in_month"] == 1050
        assert org_1_report["teams"]["3"]["local_evaluation_requests_count_in_period"] == 10
        assert org_1_report["teams"]["3"]["local_evaluation_requests_count_in_month"] == 100
        assert org_1_report["teams"]["4"]["local_evaluation_requests_count_in_period"] == 1
        assert org_1_report["teams"]["4"]["local_evaluation_requests_count_in_month"] == 5
        assert org_1_report["teams"]["3"]["billable_feature_flag_requests_count_in_period"] == 100
        assert org_1_report["teams"]["3"]["billable_feature_flag_requests_count_in_month"] == 1000
        assert org_1_report["teams"]["4"]["billable_feature_flag_requests_count_in_period"] == 10
        assert org_1_report["teams"]["4"]["billable_feature_flag_requests_count_in_month"] == 50

        # because of wrong token, Org 2 has no decide counts.
        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["local_evaluation_requests_count_in_period"] == 0
        assert org_2_report["local_evaluation_requests_count_in_month"] == 0
        assert org_1_report["decide_requests_count_in_period"] == 0
        assert org_1_report["decide_requests_count_in_month"] == 0
        assert org_2_report["billable_feature_flag_requests_count_in_month"] == 0
        assert org_2_report["billable_feature_flag_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["local_evaluation_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["local_evaluation_requests_count_in_month"] == 0
        assert org_2_report["teams"]["5"]["billable_feature_flag_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["billable_feature_flag_requests_count_in_month"] == 0


@freeze_time("2022-01-10T00:01:00Z")
class TestSurveysUsageReport(ClickhouseDestroyTablesMixin, TestCase, ClickhouseTestMixin):
    def setUp(self) -> None:
        Team.objects.all().delete()
        return super().setUp()

    def _setup_teams(self) -> None:
        self.analytics_org = Organization.objects.create(name="PostHog")
        self.org_1 = Organization.objects.create(name="Org 1")
        self.org_2 = Organization.objects.create(name="Org 2")

        self.analytics_team = Team.objects.create(pk=2, organization=self.analytics_org, name="Analytics")

        self.org_1_team_1 = Team.objects.create(pk=3, organization=self.org_1, name="Team 1 org 1")
        self.org_1_team_2 = Team.objects.create(pk=4, organization=self.org_1, name="Team 2 org 1")
        self.org_2_team_3 = Team.objects.create(pk=5, organization=self.org_2, name="Team 3 org 2")

    @patch("posthog.tasks.usage_report.Client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_usage_report_survey_responses(self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock) -> None:
        self._setup_teams()
        for i in range(10):
            _create_event(
                distinct_id="3",
                event="survey sent",
                properties={
                    "$survey_id": "seeeep-o12-as124",
                    "$survey_response": "correct",
                },
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        for i in range(5):
            _create_event(
                distinct_id="4",
                event="survey sent",
                properties={
                    "$survey_id": "see22eep-o12-as124",
                    "$survey_response": "correct",
                },
                timestamp=now() - relativedelta(hours=i),
                team=self.org_1_team_1,
            )
            _create_event(
                distinct_id="4",
                event="survey sent",
                properties={"count": 100, "token": "wrong"},
                timestamp=now() - relativedelta(hours=i),
                team=self.org_1_team_2,
            )

        for i in range(7):
            _create_event(
                distinct_id="5",
                event="survey sent",
                properties={"count": 100},
                timestamp=now() - relativedelta(hours=i),
                team=self.org_2_team_3,
            )

        # some out of range events
        _create_event(
            distinct_id="3",
            event="survey sent",
            properties={"count": 20000, "token": "correct"},
            timestamp=now() - relativedelta(days=20),
            team=self.analytics_team,
        )
        flush_persons_and_events()

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        assert len(all_reports) == 3

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )
        assert org_1_report["organization_name"] == "Org 1"
        org_2_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_2.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["survey_responses_count_in_period"] == 2
        assert org_1_report["survey_responses_count_in_month"] == 10
        assert org_1_report["teams"]["3"]["survey_responses_count_in_period"] == 1
        assert org_1_report["teams"]["3"]["survey_responses_count_in_month"] == 5
        assert org_1_report["teams"]["4"]["survey_responses_count_in_period"] == 1
        assert org_1_report["teams"]["4"]["survey_responses_count_in_month"] == 5

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["decide_requests_count_in_period"] == 0
        assert org_2_report["decide_requests_count_in_month"] == 0
        assert org_2_report["survey_responses_count_in_period"] == 1
        assert org_2_report["survey_responses_count_in_month"] == 7
        assert org_2_report["teams"]["5"]["survey_responses_count_in_period"] == 1
        assert org_2_report["teams"]["5"]["survey_responses_count_in_month"] == 7


@freeze_time("2022-01-10T00:01:00Z")
class TestExternalDataSyncUsageReport(ClickhouseDestroyTablesMixin, TestCase, ClickhouseTestMixin):
    def setUp(self) -> None:
        Team.objects.all().delete()
        return super().setUp()

    def _setup_teams(self) -> None:
        self.analytics_org = Organization.objects.create(name="PostHog")
        self.org_1 = Organization.objects.create(name="Org 1")
        self.org_2 = Organization.objects.create(name="Org 2")

        self.analytics_team = Team.objects.create(pk=2, organization=self.analytics_org, name="Analytics")

        self.org_1_team_1 = Team.objects.create(pk=3, organization=self.org_1, name="Team 1 org 1")
        self.org_1_team_2 = Team.objects.create(pk=4, organization=self.org_1, name="Team 2 org 1")
        self.org_2_team_3 = Team.objects.create(pk=5, organization=self.org_2, name="Team 3 org 2")

    @patch("posthog.tasks.usage_report.Client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_rows_synced_response(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        for i in range(5):
            start_time = (now() - relativedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            _create_event(
                distinct_id="3",
                event="external data sync job",
                properties={
                    "count": 10,
                    "job_id": 10924,
                    "startTime": start_time,
                },
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )
            # identical job id should be deduped and not counted
            _create_event(
                distinct_id="3",
                event="external data sync job",
                properties={
                    "count": 10,
                    "job_id": 10924,
                    "startTime": start_time,
                },
                timestamp=now() - relativedelta(hours=i, minutes=i),
                team=self.analytics_team,
            )

        for i in range(5):
            _create_event(
                distinct_id="4",
                event="external data sync job",
                properties={
                    "count": 10,
                    "job_id": 10924,
                    "startTime": (now() - relativedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        flush_persons_and_events()

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        assert len(all_reports) == 3

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )

        org_2_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_2.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["rows_synced_in_period"] == 20

        assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 10
        assert org_1_report["teams"]["4"]["rows_synced_in_period"] == 10

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["rows_synced_in_period"] == 0


class SendUsageTest(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.team2 = Team.objects.create(organization=self.organization)

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-08T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team2,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-10T14:01:01Z",
        )
        flush_persons_and_events()
        TEST_clear_instance_license_cache()

    def _usage_report_response(self) -> Any:
        # A roughly correct billing response
        return {
            "customer": {
                "billing_period": {
                    "current_period_start": "2021-10-01T00:00:00Z",
                    "current_period_end": "2021-10-31T00:00:00Z",
                },
                "usage_summary": {
                    "events": {"usage": 10000, "limit": None},
                    "recordings": {
                        "usage": 1000,
                        "limit": None,
                    },
                    "rows_synced": {
                        "usage": 1000,
                        "limit": None,
                    },
                },
            }
        }

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_send_usage(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.status_code = 200
        mockresponse.json = lambda: self._usage_report_response()
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        period = get_previous_day()
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)
        full_report_as_dict = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.organization.id)], get_instance_metadata(period))
        )
        send_all_org_usage_reports(dry_run=False)
        license = License.objects.first()
        assert license
        token = build_billing_token(license, self.organization)
        mock_post.assert_called_once_with(
            f"{BILLING_SERVICE_URL}/api/usage",
            json=full_report_as_dict,
            headers={"Authorization": f"Bearer {token}"},
        )

        mock_posthog.capture.assert_any_call(
            get_machine_id(),
            "organization usage report",
            {**full_report_as_dict, "scope": "machine"},
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
            mockresponse.json = lambda: self._usage_report_response()
            mock_posthog = MagicMock()
            mock_client.return_value = mock_posthog

            period = get_previous_day()
            period_start, period_end = period
            all_reports = _get_all_org_reports(period_start, period_end)
            full_report_as_dict = _get_full_org_usage_report_as_dict(
                _get_full_org_usage_report(
                    all_reports[str(self.organization.id)],
                    get_instance_metadata(period),
                )
            )
            send_all_org_usage_reports(dry_run=False)
            license = License.objects.first()
            assert license
            token = build_billing_token(license, self.organization)
            mock_post.assert_called_once_with(
                f"{BILLING_SERVICE_URL}/api/usage",
                json=full_report_as_dict,
                headers={"Authorization": f"Bearer {token}"},
            )

            mock_posthog.capture.assert_any_call(
                self.user.distinct_id,
                "organization usage report",
                {**full_report_as_dict, "scope": "user"},
                groups={
                    "instance": "http://localhost:8000",
                    "organization": str(self.organization.id),
                },
                timestamp=None,
            )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.capture_exception")
    @patch("posthog.tasks.usage_report.sync_execute", side_effect=Exception())
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_send_usage_cloud_exception(
        self,
        mock_post: MagicMock,
        mock_client: MagicMock,
        mock_sync_execute: MagicMock,
        mock_capture_exception: MagicMock,
    ) -> None:
        with pytest.raises(Exception):
            with self.is_cloud(True):
                mockresponse = Mock()
                mock_post.return_value = mockresponse
                mockresponse.status_code = 200
                mockresponse.json = lambda: self._usage_report_response()
                mock_posthog = MagicMock()
                mock_client.return_value = mock_posthog
                send_all_org_usage_reports(dry_run=False)
        assert mock_capture_exception.call_count == 1

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_send_usage_billing_service_not_reachable(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        with pytest.raises(Exception):
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
        usage_report_response = self._usage_report_response()
        mockresponse.json = lambda: usage_report_response
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        send_all_org_usage_reports(dry_run=False)

        self.team.organization.refresh_from_db()
        assert self.team.organization.usage == {
            "events": {"limit": None, "usage": 10000, "todays_usage": 0},
            "recordings": {"limit": None, "usage": 1000, "todays_usage": 0},
            "rows_synced": {"limit": None, "usage": 1000, "todays_usage": 0},
            "period": ["2021-10-01T00:00:00Z", "2021-10-31T00:00:00Z"],
        }

    @patch("posthog.tasks.usage_report.Client")
    def test_capture_event_called_with_string_timestamp(self, mock_client: MagicMock) -> None:
        organization = Organization.objects.create()
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog
        capture_event(
            mock_client,
            "test event",
            organization.id,
            {"prop1": "val1"},
            "2021-10-10T23:01:00.00Z",
        )
        assert mock_client.capture.call_args[1]["timestamp"] == datetime(2021, 10, 10, 23, 1, tzinfo=tzutc())


class SendNoUsageTest(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_usage_not_sent_if_zero(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        send_all_org_usage_reports(dry_run=False)

        mock_post.assert_not_called()


class SendUsageNoLicenseTest(APIBaseTest):
    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.Client")
    @patch("requests.post")
    def test_no_license(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        TEST_clear_instance_license_cache()
        # Same test, we just don't include the LicensedTestMixin so no license
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-08T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-10T14:01:01Z",
        )

        flush_persons_and_events()

        send_all_org_usage_reports()

        mock_post.assert_not_called()
