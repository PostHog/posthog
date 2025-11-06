import gzip
import json
import base64
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseDestroyTablesMixin,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    run_clickhouse_statement_in_parallel,
    snapshot_clickhouse_queries,
)
from unittest.mock import MagicMock, Mock, patch

from django.test import TestCase
from django.utils.timezone import now

import structlog
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc

from posthog.schema import EventsQuery

from posthog.hogql.query import execute_hogql_query

from posthog.batch_exports.models import BatchExport, BatchExportDestination, BatchExportRun
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models import Organization, Plugin, Team
from posthog.models.app_metrics2.sql import TRUNCATE_APP_METRICS2_TABLE_SQL
from posthog.models.dashboard import Dashboard
from posthog.models.event.util import create_event
from posthog.models.feature_flag import FeatureFlag
from posthog.models.group.util import create_group
from posthog.models.plugin import PluginConfig
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.tasks.usage_report import (
    OrgReport,
    _add_team_report_to_org_reports,
    _get_all_org_reports,
    _get_all_usage_data_as_team_rows,
    _get_full_org_usage_report,
    _get_full_org_usage_report_as_dict,
    _get_team_report,
    _get_teams_for_usage_reports,
    capture_event,
    get_instance_metadata,
    send_all_org_usage_reports,
)
from posthog.test.fixtures import create_app_metric2
from posthog.test.test_utils import create_group_type_mapping_without_created_at
from posthog.utils import get_previous_day

from products.data_warehouse.backend.models import (
    DataWarehouseSavedQuery,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.enterprise.backend.api.test.base import LicensedTestMixin
from products.enterprise.backend.clickhouse.materialized_columns.columns import materialize
from products.enterprise.backend.models.license import License
from products.error_tracking.backend.models import ErrorTrackingIssue

logger = structlog.get_logger(__name__)


def _setup_replay_data(team_id: int, include_mobile_replay: bool, include_zero_duration: bool = False) -> None:
    # recordings in period  - 5 sessions
    for i in range(1, 6):
        session_id = str(i)
        timestamp = now() - relativedelta(hours=12)
        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            distinct_id=str(uuid4()),
            first_timestamp=timestamp,
            last_timestamp=timestamp + timedelta(seconds=1),
            size=10,
        )

    if include_mobile_replay:
        timestamp = now() - relativedelta(hours=12)
        produce_replay_summary(
            team_id=team_id,
            session_id="a-single-mobile-recording",
            distinct_id=str(uuid4()),
            first_timestamp=timestamp,
            last_timestamp=timestamp + timedelta(seconds=1),
            snapshot_source="mobile",
            size=6,
        )

    if include_zero_duration:
        produce_replay_summary(
            team_id=team_id,
            session_id="zero-duration",
            distinct_id=str(uuid4()),
            first_timestamp=now() - relativedelta(hours=12),
            last_timestamp=now() - relativedelta(hours=12),
        )

    # recordings out of period  - 11 sessions
    for i in range(1, 11):
        id1 = str(i + 10)
        timestamp1 = now() - relativedelta(hours=48)
        produce_replay_summary(
            team_id=team_id,
            session_id=id1,
            distinct_id=str(uuid4()),
            first_timestamp=timestamp1,
            last_timestamp=timestamp1 + timedelta(seconds=1),
            size=10,
        )
        # we maybe also include a single mobile recording out of period
        if i == 1 and include_mobile_replay:
            produce_replay_summary(
                team_id=team_id,
                session_id=f"{id1}-mobile",
                distinct_id=str(uuid4()),
                first_timestamp=timestamp1,
                last_timestamp=timestamp1 + timedelta(seconds=1),
                snapshot_source="mobile",
                size=6,
            )

    # ensure there is a recording that starts before the period and ends during the period
    # report is going to be for "yesterday" relative to the test so...
    start_of_day = datetime.combine(now().date(), datetime.min.time()) - relativedelta(days=1)
    session_that_will_not_match = "session-that-will-not-match-because-it-starts-before-the-period"
    timestamp2 = start_of_day - relativedelta(hours=1)
    produce_replay_summary(
        team_id=team_id,
        session_id=session_that_will_not_match,
        distinct_id=str(uuid4()),
        first_timestamp=timestamp2,
        last_timestamp=timestamp2 + timedelta(seconds=1),
        size=10,
    )
    produce_replay_summary(
        team_id=team_id,
        session_id=session_that_will_not_match,
        distinct_id=str(uuid4()),
        first_timestamp=start_of_day,
        last_timestamp=start_of_day + timedelta(seconds=1),
        size=10,
    )
    timestamp3 = start_of_day + relativedelta(hours=1)
    produce_replay_summary(
        team_id=team_id,
        session_id=session_that_will_not_match,
        distinct_id=str(uuid4()),
        first_timestamp=timestamp3,
        last_timestamp=timestamp3 + timedelta(seconds=1),
        size=10,
    )


@freeze_time("2022-01-10T00:01:00Z")
class TestUsageReport(APIBaseTest, ClickhouseTestMixin, ClickhouseDestroyTablesMixin, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()

        # make sure we don't collapse duplicate rows
        sync_execute("SYSTEM STOP MERGES")

        # Clear existing data
        sync_execute("TRUNCATE TABLE events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE person_distinct_id")

        materialize("events", "$exception_values")

        self.expected_properties: dict = {}

    def _create_sample_usage_data(self, include_mobile_replay: bool) -> None:
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
                    properties={"$lib": "web", "$is_identified": True},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_internal_team_0,
                )

            # Events for org 1 team 1
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_1_team_1)

            _create_event(
                distinct_id=distinct_id,
                event="survey sent",
                properties={"$lib": "web", "$is_identified": True},
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

            ErrorTrackingIssue.objects.create(team=self.org_1_team_1)

            uuids = [uuid4() for _ in range(0, 10)]
            for uuid in uuids:
                create_event(
                    event_uuid=uuid,
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "web", "$is_identified": True},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_1,
                )

            # create duplicate events
            for uuid in uuids:
                _create_event(
                    event_uuid=uuid,
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "web", "$is_identified": True},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_1,
                )

            _create_event(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                properties={"$lib": "web", "$is_identified": True},
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
            create_group_type_mapping_without_created_at(
                team=self.org_1_team_1,
                project_id=self.org_1_team_1.project_id,
                group_type="organization",
                group_type_index=0,
            )
            create_group_type_mapping_without_created_at(
                team=self.org_1_team_1,
                project_id=self.org_1_team_1.project_id,
                group_type="company",
                group_type_index=1,
            )
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
                properties={"$group_0": "org:5", "$is_identified": True},
            )
            _create_event(
                event="event",
                lib="web",
                distinct_id=distinct_id,
                team=self.team,
                timestamp=now() - relativedelta(hours=12),
                properties={"$group_0": "org:6", "$is_identified": True},
            )

            # For LLM integrations
            create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event="helicone_request_response",
                properties={"$lib": "web", "$is_identified": True},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
            )

            create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event="keywords_ai_api_logging",
                properties={"$lib": "web", "$is_identified": True},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
            )

            create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event="langfuse generation",
                properties={"$lib": "web", "$is_identified": True},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
            )

            create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event="traceloop span",
                properties={"$lib": "web", "$is_identified": True},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
            )

            create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event="$ai_generation",
                properties={
                    "$ai_trace_id": "some_id",
                    "$ai_input_tokens": 100,
                    "$ai_output_tokens": 100,
                    "$ai_input_cost_usd": 0.01,
                    "$ai_output_cost_usd": 0.01,
                    "$ai_total_cost_usd": 0.02,
                },
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
            )

            # Add events for each SDK
            sdks = [
                "web",
                "js",
                "posthog-node",
                "posthog-android",
                "posthog-flutter",
                "posthog-ios",
                "posthog-go",
                "posthog-java",
                "posthog-server",
                "posthog-react-native",
                "posthog-ruby",
                "posthog-python",
                "posthog-php",
                "posthog-dotnet",
                "posthog-elixir",
            ]

            for sdk in sdks:
                create_event(
                    event_uuid=uuid4(),
                    distinct_id=distinct_id,
                    event="$pageview",
                    properties={"$lib": sdk, "$is_identified": True},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_1,
                )

            # Events for org 1 team 2
            distinct_id = str(uuid4())
            _create_person(distinct_ids=[distinct_id], team=self.org_1_team_2)

            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "web", "$is_identified": True},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_1_team_2,
                )

            _create_event(
                distinct_id=distinct_id,
                event="$eventAnonymousPersonfull",
                properties={"$lib": "web", "$is_identified": False},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_2,
                person_mode="full",
            )

            _setup_replay_data(team_id=self.org_1_team_2.id, include_mobile_replay=include_mobile_replay)

            _create_event(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                properties={"$lib": "web", "$is_identified": True},
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
                    properties={"$lib": "web", "$is_identified": True},
                    timestamp=now() - relativedelta(hours=12),
                    team=self.org_2_team_3,
                )
            _create_event(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                properties={"$lib": "web", "$is_identified": True},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_2_team_3,
            )
            _create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event="$propertyless_event",
                properties={"$lib": "web", "$is_identified": True},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
                person_mode="propertyless",
            )
            _create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event="$propertyless_event",
                properties={"$lib": "web", "$is_identified": True},
                timestamp=now() - relativedelta(hours=12),
                team=self.org_1_team_1,
                person_mode="force_upgrade",
            )

            flush_persons_and_events()

    def _select_report_by_org_id(self, org_id: str, reports: list[dict]) -> dict:
        return next(report for report in reports if report["organization_id"] == org_id)

    def _create_plugin(self, name: str, enabled: bool) -> None:
        plugin = Plugin.objects.create(organization_id=self.team.organization.pk, name=name)
        PluginConfig.objects.create(plugin=plugin, enabled=enabled, order=1)

    def _test_usage_report(self) -> list[dict]:
        with self.settings(SITE_URL="http://test.posthog.com"):
            self._create_sample_usage_data(include_mobile_replay=True)
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
                    "event_count_in_period": 42,
                    "enhanced_persons_event_count_in_period": 41,
                    "event_count_with_groups_in_period": 2,
                    "event_count_from_keywords_ai_in_period": 1,
                    "event_count_from_traceloop_in_period": 1,
                    "event_count_from_langfuse_in_period": 1,
                    "event_count_from_helicone_in_period": 1,
                    "web_events_count_in_period": 37,
                    "web_lite_events_count_in_period": 1,
                    "node_events_count_in_period": 1,
                    "android_events_count_in_period": 1,
                    "flutter_events_count_in_period": 1,
                    "ios_events_count_in_period": 1,
                    "go_events_count_in_period": 1,
                    "java_events_count_in_period": 2,
                    "react_native_events_count_in_period": 1,
                    "ruby_events_count_in_period": 1,
                    "python_events_count_in_period": 1,
                    "php_events_count_in_period": 1,
                    "dotnet_events_count_in_period": 1,
                    "elixir_events_count_in_period": 1,
                    "recording_bytes_in_period": 50,
                    "recording_count_in_period": 5,
                    "mobile_recording_bytes_in_period": 6,
                    "mobile_recording_count_in_period": 1,
                    "mobile_billable_recording_count_in_period": 0,
                    "group_types_total": 2,
                    "dashboard_count": 2,
                    "dashboard_template_count": 0,
                    "dashboard_shared_count": 1,
                    "dashboard_tagged_count": 0,
                    "ff_count": 2,
                    "ff_active_count": 1,
                    "issues_created_total": 1,
                    "symbol_sets_count": 0,
                    "resolved_symbol_sets_count": 0,
                    "decide_requests_count_in_period": 0,
                    "local_evaluation_requests_count_in_period": 0,
                    "billable_feature_flag_requests_count_in_period": 0,
                    "survey_responses_count_in_period": 1,
                    "query_app_bytes_read": 0,
                    "query_app_rows_read": 0,
                    "query_app_duration_ms": 0,
                    "query_api_bytes_read": 0,
                    "query_api_rows_read": 0,
                    "query_api_duration_ms": 0,
                    "event_explorer_app_bytes_read": 0,
                    "event_explorer_app_rows_read": 0,
                    "event_explorer_app_duration_ms": 0,
                    "event_explorer_api_bytes_read": 0,
                    "event_explorer_api_rows_read": 0,
                    "event_explorer_api_duration_ms": 0,
                    "rows_synced_in_period": 0,
                    "exceptions_captured_in_period": 0,
                    "ai_event_count_in_period": 1,
                    "hog_function_calls_in_period": 0,
                    "hog_function_fetch_calls_in_period": 0,
                    "cdp_billable_invocations_in_period": 0,
                    "rows_exported_in_period": 0,
                    "date": "2022-01-09",
                    "organization_id": str(self.organization.id),
                    "organization_name": "Test",
                    "organization_created_at": "2022-01-10T00:01:00+00:00",
                    "organization_user_count": 1,
                    "team_count": 2,
                    "teams": {
                        str(self.org_1_team_1.id): {
                            "event_count_in_period": 31,
                            "enhanced_persons_event_count_in_period": 30,
                            "event_count_with_groups_in_period": 2,
                            "event_count_from_keywords_ai_in_period": 1,
                            "event_count_from_traceloop_in_period": 1,
                            "event_count_from_langfuse_in_period": 1,
                            "event_count_from_helicone_in_period": 1,
                            "web_events_count_in_period": 25,
                            "web_lite_events_count_in_period": 1,
                            "node_events_count_in_period": 1,
                            "android_events_count_in_period": 1,
                            "flutter_events_count_in_period": 1,
                            "ios_events_count_in_period": 1,
                            "go_events_count_in_period": 1,
                            "java_events_count_in_period": 2,
                            "react_native_events_count_in_period": 1,
                            "ruby_events_count_in_period": 1,
                            "python_events_count_in_period": 1,
                            "php_events_count_in_period": 1,
                            "dotnet_events_count_in_period": 1,
                            "elixir_events_count_in_period": 1,
                            "recording_bytes_in_period": 0,
                            "recording_count_in_period": 0,
                            "mobile_recording_bytes_in_period": 0,
                            "mobile_recording_count_in_period": 0,
                            "mobile_billable_recording_count_in_period": 0,
                            "group_types_total": 2,
                            "dashboard_count": 2,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 1,
                            "dashboard_tagged_count": 0,
                            "ff_count": 2,
                            "ff_active_count": 1,
                            "issues_created_total": 1,
                            "symbol_sets_count": 0,
                            "resolved_symbol_sets_count": 0,
                            "decide_requests_count_in_period": 0,
                            "local_evaluation_requests_count_in_period": 0,
                            "billable_feature_flag_requests_count_in_period": 0,
                            "survey_responses_count_in_period": 1,
                            "query_app_bytes_read": 0,
                            "query_app_rows_read": 0,
                            "query_app_duration_ms": 0,
                            "query_api_bytes_read": 0,
                            "query_api_rows_read": 0,
                            "query_api_duration_ms": 0,
                            "event_explorer_app_bytes_read": 0,
                            "event_explorer_app_rows_read": 0,
                            "event_explorer_app_duration_ms": 0,
                            "event_explorer_api_bytes_read": 0,
                            "event_explorer_api_rows_read": 0,
                            "event_explorer_api_duration_ms": 0,
                            "rows_synced_in_period": 0,
                            "exceptions_captured_in_period": 0,
                            "hog_function_calls_in_period": 0,
                            "hog_function_fetch_calls_in_period": 0,
                            "cdp_billable_invocations_in_period": 0,
                            "rows_exported_in_period": 0,
                            "ai_event_count_in_period": 1,
                        },
                        str(self.org_1_team_2.id): {
                            "event_count_in_period": 11,
                            "enhanced_persons_event_count_in_period": 11,
                            "event_count_with_groups_in_period": 0,
                            "event_count_from_keywords_ai_in_period": 0,
                            "event_count_from_traceloop_in_period": 0,
                            "event_count_from_langfuse_in_period": 0,
                            "event_count_from_helicone_in_period": 0,
                            "web_events_count_in_period": 12,
                            "web_lite_events_count_in_period": 0,
                            "node_events_count_in_period": 0,
                            "android_events_count_in_period": 0,
                            "flutter_events_count_in_period": 0,
                            "ios_events_count_in_period": 0,
                            "go_events_count_in_period": 0,
                            "java_events_count_in_period": 0,
                            "react_native_events_count_in_period": 0,
                            "ruby_events_count_in_period": 0,
                            "python_events_count_in_period": 0,
                            "php_events_count_in_period": 0,
                            "dotnet_events_count_in_period": 0,
                            "elixir_events_count_in_period": 0,
                            "recording_bytes_in_period": 50,
                            "recording_count_in_period": 5,
                            "mobile_recording_bytes_in_period": 6,
                            "mobile_recording_count_in_period": 1,
                            "mobile_billable_recording_count_in_period": 0,
                            "group_types_total": 0,
                            "dashboard_count": 0,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 0,
                            "dashboard_tagged_count": 0,
                            "ff_count": 0,
                            "ff_active_count": 0,
                            "issues_created_total": 0,
                            "symbol_sets_count": 0,
                            "resolved_symbol_sets_count": 0,
                            "decide_requests_count_in_period": 0,
                            "local_evaluation_requests_count_in_period": 0,
                            "billable_feature_flag_requests_count_in_period": 0,
                            "survey_responses_count_in_period": 0,
                            "query_app_bytes_read": 0,
                            "query_app_rows_read": 0,
                            "query_app_duration_ms": 0,
                            "query_api_bytes_read": 0,
                            "query_api_rows_read": 0,
                            "query_api_duration_ms": 0,
                            "event_explorer_app_bytes_read": 0,
                            "event_explorer_app_rows_read": 0,
                            "event_explorer_app_duration_ms": 0,
                            "event_explorer_api_bytes_read": 0,
                            "event_explorer_api_rows_read": 0,
                            "event_explorer_api_duration_ms": 0,
                            "rows_synced_in_period": 0,
                            "exceptions_captured_in_period": 0,
                            "hog_function_calls_in_period": 0,
                            "hog_function_fetch_calls_in_period": 0,
                            "cdp_billable_invocations_in_period": 0,
                            "rows_exported_in_period": 0,
                            "ai_event_count_in_period": 0,
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
                    "event_count_in_period": 10,
                    "enhanced_persons_event_count_in_period": 10,
                    "event_count_with_groups_in_period": 0,
                    "event_count_from_keywords_ai_in_period": 0,
                    "event_count_from_traceloop_in_period": 0,
                    "event_count_from_langfuse_in_period": 0,
                    "event_count_from_helicone_in_period": 0,
                    "web_events_count_in_period": 11,
                    "web_lite_events_count_in_period": 0,
                    "node_events_count_in_period": 0,
                    "android_events_count_in_period": 0,
                    "flutter_events_count_in_period": 0,
                    "ios_events_count_in_period": 0,
                    "go_events_count_in_period": 0,
                    "java_events_count_in_period": 0,
                    "react_native_events_count_in_period": 0,
                    "ruby_events_count_in_period": 0,
                    "python_events_count_in_period": 0,
                    "php_events_count_in_period": 0,
                    "dotnet_events_count_in_period": 0,
                    "elixir_events_count_in_period": 0,
                    "recording_bytes_in_period": 0,
                    "recording_count_in_period": 0,
                    "mobile_recording_bytes_in_period": 0,
                    "mobile_recording_count_in_period": 0,
                    "mobile_billable_recording_count_in_period": 0,
                    "group_types_total": 0,
                    "dashboard_count": 0,
                    "dashboard_template_count": 0,
                    "dashboard_shared_count": 0,
                    "dashboard_tagged_count": 0,
                    "ff_count": 0,
                    "ff_active_count": 0,
                    "issues_created_total": 0,
                    "symbol_sets_count": 0,
                    "resolved_symbol_sets_count": 0,
                    "decide_requests_count_in_period": 0,
                    "local_evaluation_requests_count_in_period": 0,
                    "billable_feature_flag_requests_count_in_period": 0,
                    "survey_responses_count_in_period": 0,
                    "query_app_bytes_read": 0,
                    "query_app_rows_read": 0,
                    "query_app_duration_ms": 0,
                    "query_api_bytes_read": 0,
                    "query_api_rows_read": 0,
                    "query_api_duration_ms": 0,
                    "event_explorer_app_bytes_read": 0,
                    "event_explorer_app_rows_read": 0,
                    "event_explorer_app_duration_ms": 0,
                    "event_explorer_api_bytes_read": 0,
                    "event_explorer_api_rows_read": 0,
                    "event_explorer_api_duration_ms": 0,
                    "rows_synced_in_period": 0,
                    "exceptions_captured_in_period": 0,
                    "hog_function_calls_in_period": 0,
                    "hog_function_fetch_calls_in_period": 0,
                    "cdp_billable_invocations_in_period": 0,
                    "rows_exported_in_period": 0,
                    "ai_event_count_in_period": 0,
                    "date": "2022-01-09",
                    "organization_id": str(self.org_2.id),
                    "organization_name": "Org 2",
                    "organization_created_at": "2022-01-10T00:01:00+00:00",
                    "organization_user_count": 0,
                    "team_count": 1,
                    "teams": {
                        str(self.org_2_team_3.id): {
                            "event_count_in_period": 10,
                            "enhanced_persons_event_count_in_period": 10,
                            "event_count_with_groups_in_period": 0,
                            "event_count_from_keywords_ai_in_period": 0,
                            "event_count_from_traceloop_in_period": 0,
                            "event_count_from_langfuse_in_period": 0,
                            "event_count_from_helicone_in_period": 0,
                            "web_events_count_in_period": 11,
                            "web_lite_events_count_in_period": 0,
                            "node_events_count_in_period": 0,
                            "android_events_count_in_period": 0,
                            "flutter_events_count_in_period": 0,
                            "ios_events_count_in_period": 0,
                            "go_events_count_in_period": 0,
                            "java_events_count_in_period": 0,
                            "react_native_events_count_in_period": 0,
                            "ruby_events_count_in_period": 0,
                            "python_events_count_in_period": 0,
                            "php_events_count_in_period": 0,
                            "dotnet_events_count_in_period": 0,
                            "elixir_events_count_in_period": 0,
                            "recording_bytes_in_period": 0,
                            "recording_count_in_period": 0,
                            "mobile_recording_bytes_in_period": 0,
                            "mobile_recording_count_in_period": 0,
                            "mobile_billable_recording_count_in_period": 0,
                            "group_types_total": 0,
                            "dashboard_count": 0,
                            "dashboard_template_count": 0,
                            "dashboard_shared_count": 0,
                            "dashboard_tagged_count": 0,
                            "ff_count": 0,
                            "ff_active_count": 0,
                            "issues_created_total": 0,
                            "symbol_sets_count": 0,
                            "resolved_symbol_sets_count": 0,
                            "decide_requests_count_in_period": 0,
                            "local_evaluation_requests_count_in_period": 0,
                            "billable_feature_flag_requests_count_in_period": 0,
                            "survey_responses_count_in_period": 0,
                            "query_app_bytes_read": 0,
                            "query_app_rows_read": 0,
                            "query_app_duration_ms": 0,
                            "query_api_bytes_read": 0,
                            "query_api_rows_read": 0,
                            "query_api_duration_ms": 0,
                            "event_explorer_app_bytes_read": 0,
                            "event_explorer_app_rows_read": 0,
                            "event_explorer_app_duration_ms": 0,
                            "event_explorer_api_bytes_read": 0,
                            "event_explorer_api_rows_read": 0,
                            "event_explorer_api_duration_ms": 0,
                            "rows_synced_in_period": 0,
                            "active_external_data_schemas_in_period": 0,
                            "active_batch_exports_in_period": 0,
                            "exceptions_captured_in_period": 0,
                            "hog_function_calls_in_period": 0,
                            "hog_function_fetch_calls_in_period": 0,
                            "cdp_billable_invocations_in_period": 0,
                            "rows_exported_in_period": 0,
                            "ai_event_count_in_period": 0,
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
    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_unlicensed_usage_report(self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock) -> None:
        self.expected_properties = {}
        mockresponse = Mock()
        mock_get_sqs_producer.return_value = MagicMock()
        mockresponse.status_code = 200
        mockresponse.json = lambda: {}
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        with self.settings(SITE_URL="http://test.posthog.com", EE_AVAILABLE=False):
            send_all_org_usage_reports()

        # Check calls to other services
        mock_get_sqs_producer.assert_not_called()

        # calls = [
        #     call(
        #         get_machine_id(),
        #         "organization usage report",
        #         {**all_reports[0], "scope": "machine"},
        #         groups={"instance": ANY},
        #         timestamp=None,
        #     ),
        #     call(
        #         get_machine_id(),
        #         "organization usage report",
        #         {**all_reports[1], "scope": "machine"},
        #         groups={"instance": ANY},
        #         timestamp=None,
        #     ),
        # ]

        # assert mock_posthog.capture.call_count == 2
        # mock_posthog.capture.assert_has_calls(calls, any_order=True)


@freeze_time("2022-01-09T00:01:00Z")
class TestReplayUsageReport(APIBaseTest, ClickhouseTestMixin, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()
        materialize("events", "$exception_values")

    @also_test_with_materialized_columns(event_properties=["$lib", "$exception_values"], verify_no_jsonextract=False)
    def test_usage_report_replay(self) -> None:
        _setup_replay_data(self.team.pk, include_mobile_replay=False)

        period = get_previous_day()
        period_start, period_end = period

        all_reports = _get_all_usage_data_as_team_rows(period_start, period_end)
        report = _get_team_report(all_reports, self.team)

        assert report.recording_count_in_period == 5
        assert report.mobile_recording_count_in_period == 0
        assert report.zero_duration_recording_count_in_period == 0

        org_reports: dict[str, OrgReport] = {}
        _add_team_report_to_org_reports(org_reports, self.team, report, period_start)

        assert org_reports[str(self.organization.id)].recording_count_in_period == 5
        assert org_reports[str(self.organization.id)].mobile_recording_count_in_period == 0
        assert org_reports[str(self.organization.id)].mobile_billable_recording_count_in_period == 0

    @also_test_with_materialized_columns(event_properties=["$lib", "$exception_values"], verify_no_jsonextract=False)
    def test_usage_report_replay_with_zero_duration(self) -> None:
        _setup_replay_data(self.team.pk, include_mobile_replay=False, include_zero_duration=True)

        period = get_previous_day()
        period_start, period_end = period

        all_reports = _get_all_usage_data_as_team_rows(period_start, period_end)
        report = _get_team_report(all_reports, self.team)

        assert report.recording_count_in_period == 6
        assert report.mobile_recording_count_in_period == 0
        assert report.zero_duration_recording_count_in_period == 1

        org_reports: dict[str, OrgReport] = {}
        _add_team_report_to_org_reports(org_reports, self.team, report, period_start)

        assert org_reports[str(self.organization.id)].recording_count_in_period == 6
        assert org_reports[str(self.organization.id)].mobile_recording_count_in_period == 0
        assert org_reports[str(self.organization.id)].mobile_billable_recording_count_in_period == 0
        assert org_reports[str(self.organization.id)].zero_duration_recording_count_in_period == 1

    @also_test_with_materialized_columns(event_properties=["$lib", "$exception_values"], verify_no_jsonextract=False)
    def test_usage_report_replay_with_mobile(self) -> None:
        _setup_replay_data(self.team.pk, include_mobile_replay=True)

        period = get_previous_day()
        period_start, period_end = period

        all_reports = _get_all_usage_data_as_team_rows(period_start, period_end)
        report = _get_team_report(all_reports, self.team)

        # but we do split them out of the daily usage since that field is used
        assert report.recording_count_in_period == 5
        assert report.mobile_recording_count_in_period == 1
        assert report.mobile_billable_recording_count_in_period == 0
        org_reports: dict[str, OrgReport] = {}
        _add_team_report_to_org_reports(org_reports, self.team, report, period_start)

        assert org_reports[str(self.organization.id)].recording_count_in_period == 5
        assert org_reports[str(self.organization.id)].mobile_recording_count_in_period == 1
        assert org_reports[str(self.organization.id)].mobile_billable_recording_count_in_period == 0

    @also_test_with_materialized_columns(event_properties=["$lib", "$exception_values"], verify_no_jsonextract=False)
    def test_usage_report_replay_with_billable_mobile(self) -> None:
        _setup_replay_data(self.team.pk, include_mobile_replay=True)

        # Create additional mobile replay data with proper libraries
        timestamp = now() - relativedelta(hours=12)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="billable-mobile-ios",
            distinct_id=str(uuid4()),
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            snapshot_source="mobile",
            snapshot_library="posthog-ios",
        )
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="billable-mobile-android",
            distinct_id=str(uuid4()),
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            snapshot_source="mobile",
            snapshot_library="posthog-android",
        )
        # This will be ignored
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="billable-mobile-unknown-library",
            distinct_id=str(uuid4()),
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            snapshot_source="mobile",
            snapshot_library="unknown-library",
        )

        period = get_previous_day()
        period_start, period_end = period

        all_reports = _get_all_usage_data_as_team_rows(period_start, period_end)
        report = _get_team_report(all_reports, self.team)

        # Regular mobile recordings (non-billable) + billable ones
        assert report.recording_count_in_period == 5  # web recordings
        assert report.mobile_recording_count_in_period == 4  # 1 non-billable + 2 billable + 1 from _setup_replay_data
        assert report.mobile_billable_recording_count_in_period == 2  # iOS and Android recordings

        org_reports: dict[str, OrgReport] = {}
        _add_team_report_to_org_reports(org_reports, self.team, report, period_start)

        assert org_reports[str(self.organization.id)].recording_count_in_period == 5
        assert org_reports[str(self.organization.id)].mobile_recording_count_in_period == 4
        assert org_reports[str(self.organization.id)].mobile_billable_recording_count_in_period == 2


class TestHogQLUsageReport(APIBaseTest, ClickhouseTestMixin, ClickhouseDestroyTablesMixin):
    # @also_test_with_materialized_columns(event_properties=["$lib", "$exception_values"], verify_no_jsonextract=False)
    @pytest.mark.skip(reason="Skipping due to flakiness")
    def test_usage_report_hogql_queries(self) -> None:
        for _ in range(0, 100):
            _create_event(
                distinct_id="hello",
                event="$event1",
                properties={"$lib": "web"},
                timestamp=now() - relativedelta(hours=12),
                team=self.team,
            )
        flush_persons_and_events()
        sync_execute("SYSTEM FLUSH LOGS")
        sync_execute("TRUNCATE TABLE system.query_log")

        execute_hogql_query(
            query="select * from events limit 400",
            team=self.team,
            query_type="HogQLQuery",
        )
        EventsQueryRunner(query=EventsQuery(select=["event"], limit=50), team=self.team).calculate()
        sync_execute("SYSTEM FLUSH LOGS")

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_usage_data_as_team_rows(period_start, period_end)

        report = _get_team_report(all_reports, self.team)

        # Assertions depend on query log entries being available, which can be flaky in CI
        with self.retry_assertion():
            # We selected 400 rows, but still read 200 rows to return the query
            assert report.query_app_rows_read == 200
            assert report.query_app_bytes_read > 0
            # We selected 50 rows, but still read 100 rows to return the query
            assert report.event_explorer_app_rows_read == 100
            assert report.event_explorer_app_bytes_read > 0

            # Nothing was read via the API
            assert report.query_api_rows_read == 0
            assert report.event_explorer_api_rows_read == 0

    # @also_test_with_materialized_columns(event_properties=["$lib", "$exception_values"], verify_no_jsonextract=False)
    @pytest.mark.skip(reason="Skipping due to flakiness")
    def test_usage_report_api_queries(self) -> None:
        for _ in range(0, 100):
            _create_event(
                distinct_id="hello",
                event="$event1",
                properties={"$lib": "web"},
                timestamp=now() - relativedelta(hours=12),
                team=self.team,
            )
        flush_persons_and_events()
        sync_execute("SYSTEM FLUSH LOGS")
        sync_execute("TRUNCATE TABLE system.query_log")
        tag_queries(kind="request", id="1", access_method="personal_api_key", chargeable=1)

        execute_hogql_query(
            query="select * from events limit 400",
            team=self.team,
            query_type="HogQLQuery",
        )
        EventsQueryRunner(query=EventsQuery(select=["event"], limit=50), team=self.team).calculate()
        sync_execute("SYSTEM FLUSH LOGS")

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_usage_data_as_team_rows(period_start, period_end)

        report = _get_team_report(all_reports, self.team)

        # Assertions depend on query log entries being available, which can be flaky in CI
        with self.retry_assertion():
            # No queries were read via the app
            assert report.query_app_rows_read == 0
            assert report.query_app_bytes_read == 0
            assert report.event_explorer_app_rows_read == 0
            assert report.event_explorer_app_bytes_read == 0

            # Queries were read via the API
            assert report.query_api_rows_read == 200
            assert report.event_explorer_api_rows_read == 100
            assert report.api_queries_query_count == 2
            assert report.api_queries_bytes_read > 16000  # locally it's about 16753


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
        materialize("events", "$exception_values")

    @snapshot_clickhouse_queries
    @patch("posthog.tasks.usage_report.get_ph_client")
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
        assert org_1_report["billable_feature_flag_requests_count_in_period"] == 11
        assert org_1_report["teams"]["3"]["decide_requests_count_in_period"] == 10
        assert org_1_report["teams"]["3"]["billable_feature_flag_requests_count_in_period"] == 10
        assert org_1_report["teams"]["4"]["decide_requests_count_in_period"] == 1
        assert org_1_report["teams"]["4"]["billable_feature_flag_requests_count_in_period"] == 1

        # because of wrong token, Org 2 has no decide counts.
        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["decide_requests_count_in_period"] == 0
        assert org_2_report["billable_feature_flag_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["decide_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["billable_feature_flag_requests_count_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
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
        assert org_1_report["decide_requests_count_in_period"] == 0
        assert org_1_report["billable_feature_flag_requests_count_in_period"] == 110
        assert org_1_report["teams"]["3"]["local_evaluation_requests_count_in_period"] == 10
        assert org_1_report["teams"]["4"]["local_evaluation_requests_count_in_period"] == 1
        assert org_1_report["teams"]["3"]["billable_feature_flag_requests_count_in_period"] == 100
        assert org_1_report["teams"]["4"]["billable_feature_flag_requests_count_in_period"] == 10

        # because of wrong token, Org 2 has no decide counts.
        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["local_evaluation_requests_count_in_period"] == 0
        assert org_1_report["decide_requests_count_in_period"] == 0
        assert org_2_report["billable_feature_flag_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["local_evaluation_requests_count_in_period"] == 0
        assert org_2_report["teams"]["5"]["billable_feature_flag_requests_count_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_active_hog_destinations_and_transformations_per_team(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType

        self._setup_teams()

        # Team 1: 2 active destinations, 1 active transformation
        HogFunction.objects.create(
            team=self.org_1_team_1, type=HogFunctionType.DESTINATION, enabled=True, deleted=False, name="Dest 1"
        )
        HogFunction.objects.create(
            team=self.org_1_team_1, type=HogFunctionType.DESTINATION, enabled=True, deleted=False, name="Dest 2"
        )
        HogFunction.objects.create(
            team=self.org_1_team_1, type=HogFunctionType.TRANSFORMATION, enabled=True, deleted=False, name="Trans 1"
        )
        # Team 2: 1 active destination, 2 active transformations
        HogFunction.objects.create(
            team=self.org_1_team_2, type=HogFunctionType.DESTINATION, enabled=True, deleted=False, name="Dest 3"
        )
        HogFunction.objects.create(
            team=self.org_1_team_2, type=HogFunctionType.TRANSFORMATION, enabled=True, deleted=False, name="Trans 2"
        )
        HogFunction.objects.create(
            team=self.org_1_team_2, type=HogFunctionType.TRANSFORMATION, enabled=True, deleted=False, name="Trans 3"
        )
        # Add some inactive/deleted ones (should not be counted)
        HogFunction.objects.create(
            team=self.org_1_team_1, type=HogFunctionType.DESTINATION, enabled=False, deleted=False, name="Inactive Dest"
        )
        HogFunction.objects.create(
            team=self.org_1_team_2,
            type=HogFunctionType.TRANSFORMATION,
            enabled=True,
            deleted=True,
            name="Deleted Trans",
        )

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)
        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )

        assert org_1_report["teams"][str(self.org_1_team_1.id)]["active_hog_destinations_in_period"] == 2
        assert org_1_report["teams"][str(self.org_1_team_1.id)]["active_hog_transformations_in_period"] == 1
        assert org_1_report["teams"][str(self.org_1_team_2.id)]["active_hog_destinations_in_period"] == 1
        assert org_1_report["teams"][str(self.org_1_team_2.id)]["active_hog_transformations_in_period"] == 2


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
        materialize("events", "$exception_values")

    @patch("posthog.tasks.usage_report.get_ph_client")
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
        assert org_1_report["teams"]["3"]["survey_responses_count_in_period"] == 1
        assert org_1_report["teams"]["4"]["survey_responses_count_in_period"] == 1

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["decide_requests_count_in_period"] == 0
        assert org_2_report["survey_responses_count_in_period"] == 1
        assert org_2_report["teams"]["5"]["survey_responses_count_in_period"] == 1

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_survey_events_are_not_double_charged(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()
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
                event="survey shown",
                timestamp=now() - relativedelta(hours=i),
                team=self.org_1_team_1,
            )
            _create_event(
                distinct_id="4",
                event="survey dismissed",
                timestamp=now() - relativedelta(hours=i),
                team=self.org_1_team_1,
            )
        flush_persons_and_events()
        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)
        report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )
        assert report["organization_name"] == "Org 1"
        assert report["event_count_in_period"] == 0


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
        materialize("events", "$exception_values")

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_rows_synced_free_period_response(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        with freeze_time("2025-11-01T00:00:00Z"):
            self._setup_teams()

            source = ExternalDataSource.objects.create(
                team_id=3,
                source_id="source_id",
                connection_id="connection_id",
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.STRIPE,
            )

            for _ in range(5):
                ExternalDataJob.objects.create(
                    team_id=3,
                    finished_at=now(),
                    rows_synced=10,
                    status=ExternalDataJob.Status.COMPLETED,
                    pipeline=source,
                    pipeline_version=ExternalDataJob.PipelineVersion.V1,
                )

            for _ in range(5):
                ExternalDataJob.objects.create(
                    team_id=4,
                    finished_at=now(),
                    rows_synced=10,
                    status=ExternalDataJob.Status.COMPLETED,
                    pipeline=source,
                    pipeline_version=ExternalDataJob.PipelineVersion.V1,
                )

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
            assert org_1_report["rows_synced_in_period"] == 0
            assert org_1_report["free_historical_rows_synced_in_period"] == 100

            assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 0
            assert org_1_report["teams"]["3"]["free_historical_rows_synced_in_period"] == 50
            assert org_1_report["teams"]["4"]["rows_synced_in_period"] == 0
            assert org_1_report["teams"]["4"]["free_historical_rows_synced_in_period"] == 50

            assert org_2_report["organization_name"] == "Org 2"
            assert org_2_report["rows_synced_in_period"] == 0
            assert org_2_report["free_historical_rows_synced_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_rows_synced_after_free_period_response(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        with freeze_time("2025-10-30T00:00:00Z"):
            source_4 = ExternalDataSource.objects.create(
                team_id=4,
                source_id="source_id_2",
                connection_id="connection_id_2",
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.STRIPE,
            )

        with freeze_time("2025-11-07T01:00:00Z"):
            source_3 = ExternalDataSource.objects.create(
                team_id=3,
                source_id="source_id",
                connection_id="connection_id",
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.STRIPE,
            )

            for _ in range(5):
                ExternalDataJob.objects.create(
                    team_id=3,
                    finished_at=now(),
                    rows_synced=10,
                    status=ExternalDataJob.Status.COMPLETED,
                    pipeline=source_3,
                    pipeline_version=ExternalDataJob.PipelineVersion.V1,
                )

            for _ in range(5):
                ExternalDataJob.objects.create(
                    team_id=4,
                    finished_at=now(),
                    rows_synced=10,
                    status=ExternalDataJob.Status.COMPLETED,
                    pipeline=source_4,
                    pipeline_version=ExternalDataJob.PipelineVersion.V1,
                )

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
            assert org_1_report["rows_synced_in_period"] == 50
            assert org_1_report["free_historical_rows_synced_in_period"] == 50

            # Team 3 has a new pipeline (< 7 days old), gets free historical rows
            assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 0
            assert org_1_report["teams"]["3"]["free_historical_rows_synced_in_period"] == 50

            # Team 4 is past free period
            assert org_1_report["teams"]["4"]["rows_synced_in_period"] == 50
            assert org_1_report["teams"]["4"]["free_historical_rows_synced_in_period"] == 0

            assert org_2_report["organization_name"] == "Org 2"
            assert org_2_report["rows_synced_in_period"] == 0
            assert org_2_report["free_historical_rows_synced_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_rows_synced_before_free_period_response(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        with freeze_time("2025-10-28T23:59:00Z"):
            self._setup_teams()

            source = ExternalDataSource.objects.create(
                team_id=3,
                source_id="source_id",
                connection_id="connection_id",
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.STRIPE,
            )

            for _ in range(5):
                ExternalDataJob.objects.create(
                    team_id=3,
                    finished_at=now(),
                    rows_synced=10,
                    status=ExternalDataJob.Status.COMPLETED,
                    pipeline=source,
                    pipeline_version=ExternalDataJob.PipelineVersion.V1,
                )

            for _ in range(5):
                ExternalDataJob.objects.create(
                    team_id=4,
                    finished_at=now(),
                    rows_synced=10,
                    status=ExternalDataJob.Status.COMPLETED,
                    pipeline=source,
                    pipeline_version=ExternalDataJob.PipelineVersion.V1,
                )

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
            assert org_1_report["rows_synced_in_period"] == 100
            assert org_1_report["free_historical_rows_synced_in_period"] == 100

            assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 50
            assert org_1_report["teams"]["3"]["free_historical_rows_synced_in_period"] == 50
            assert org_1_report["teams"]["4"]["rows_synced_in_period"] == 50
            assert org_1_report["teams"]["4"]["free_historical_rows_synced_in_period"] == 50

            assert org_2_report["organization_name"] == "Org 2"
            assert org_2_report["rows_synced_in_period"] == 0
            assert org_2_report["free_historical_rows_synced_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_rows_synced_response(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        source = ExternalDataSource.objects.create(
            team_id=3,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=3,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.COMPLETED,
                pipeline=source,
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=4,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.COMPLETED,
                pipeline=source,
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

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
        assert org_1_report["rows_synced_in_period"] == 100

        assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 50
        assert org_1_report["teams"]["4"]["rows_synced_in_period"] == 50

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["rows_synced_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_free_historical_rows_synced_response(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        # Free historical rows
        free_source = ExternalDataSource.objects.create(
            team_id=3,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=3,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.COMPLETED,
                pipeline=free_source,
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

        # Non-free-historical rows
        non_free_source = ExternalDataSource.objects.create(
            team_id=3,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        non_free_source.created_at = now() - timedelta(days=21)
        non_free_source.save()

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=3,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.COMPLETED,
                pipeline=non_free_source,
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

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
        assert org_1_report["rows_synced_in_period"] == 100

        assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 100
        assert org_1_report["teams"]["3"]["free_historical_rows_synced_in_period"] == 50

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["rows_synced_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_active_external_data_schemas_in_period(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        # created at doesn't matter. just what's running or completed at run time
        self._setup_teams()

        source = ExternalDataSource.objects.create(
            team_id=3,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        for _ in range(5):
            ExternalDataSchema.objects.create(
                team_id=3,
                status=ExternalDataSchema.Status.RUNNING,
                source=source,
            )

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        assert len(all_reports) == 3

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["active_external_data_schemas_in_period"] == 5

        org_2_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_2.id)], get_instance_metadata(period))
        )

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["active_external_data_schemas_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_active_batch_exports_in_period(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        # created at doesn't matter. just what's running or completed at run time
        self._setup_teams()

        batch_export_destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.S3, config={"bucket_name": "my_production_s3_bucket"}
        )
        BatchExport.objects.create(team_id=3, name="A batch export", destination=batch_export_destination, paused=False)

        BatchExport.objects.create(
            team=self.analytics_team, name="A batch export", destination=batch_export_destination, paused=False
        )

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        assert len(all_reports) == 3

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["active_batch_exports_in_period"] == 1

        org_2_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_2.id)], get_instance_metadata(period))
        )

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["active_batch_exports_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_batch_export_rows_exported_in_period(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        batch_export_destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.S3, config={"bucket_name": "test_bucket"}
        )
        batch_export = BatchExport.objects.create(
            team_id=3,
            name="Test export",
            destination=batch_export_destination,
            paused=False,
            model=BatchExport.Model.EVENTS,
        )

        for i in range(3):
            BatchExportRun.objects.create(
                batch_export=batch_export,
                data_interval_end=now() - timedelta(hours=i),
                data_interval_start=now() - timedelta(hours=i + 1),
                finished_at=now(),
                status=BatchExportRun.Status.COMPLETED,
                records_completed=100 * (i + 1),  # 100, 200, 300
            )

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        assert len(all_reports) == 3

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["rows_exported_in_period"] == 600
        assert org_1_report["teams"]["3"]["rows_exported_in_period"] == 600

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_rows_synced_failed_jobs(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        source = ExternalDataSource.objects.create(
            team=self.analytics_team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=3,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.COMPLETED,
                pipeline=source,
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=4,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.FAILED,
                pipeline=source,
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

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
        assert org_1_report["rows_synced_in_period"] == 50

        assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 50
        assert org_1_report["teams"]["4"]["rows_synced_in_period"] == 0

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["rows_synced_in_period"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_external_data_rows_synced_response_with_v2_jobs(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        source = ExternalDataSource.objects.create(
            team=self.analytics_team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=3,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.COMPLETED,
                pipeline=source,
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

        for _ in range(5):
            ExternalDataJob.objects.create(
                team_id=4,
                finished_at=now(),
                rows_synced=10,
                status=ExternalDataJob.Status.COMPLETED,
                pipeline=source,
                pipeline_version=ExternalDataJob.PipelineVersion.V2,
                billable=False,
            )

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
        assert org_1_report["rows_synced_in_period"] == 50

        assert org_1_report["teams"]["3"]["rows_synced_in_period"] == 50
        assert org_1_report["teams"]["4"]["rows_synced_in_period"] == 0  # V2 pipelines

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["rows_synced_in_period"] == 0


@freeze_time("2022-01-10T00:01:00Z")
class TestDWHStorageUsageReport(ClickhouseDestroyTablesMixin, TestCase, ClickhouseTestMixin):
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
        materialize("events", "$exception_values")

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_data_in_s3_response(self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock) -> None:
        self._setup_teams()

        source = ExternalDataSource.objects.create(team_id=3, source_type="Stripe")

        for _ in range(5):
            DataWarehouseTable.objects.create(
                team_id=3,
                size_in_s3_mib=1,
                external_data_source_id=source.id,
            )

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
        assert org_1_report["dwh_tables_storage_in_s3_in_mib"] == 5.0

        assert org_1_report["teams"]["3"]["dwh_tables_storage_in_s3_in_mib"] == 5.0
        assert org_1_report["teams"]["3"]["dwh_total_storage_in_s3_in_mib"] == 5.0
        assert org_1_report["teams"]["3"]["dwh_mat_views_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_tables_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_total_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_mat_views_storage_in_s3_in_mib"] == 0

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["dwh_tables_storage_in_s3_in_mib"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_data_in_s3_response_with_deleted_tables(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        source = ExternalDataSource.objects.create(team_id=3, source_type="Stripe")

        for _ in range(5):
            DataWarehouseTable.objects.create(
                team_id=3,
                size_in_s3_mib=1,
                external_data_source_id=source.id,
            )

        DataWarehouseTable.objects.create(team_id=3, size_in_s3_mib=10, deleted=True)
        DataWarehouseTable.objects.create(team_id=3, size_in_s3_mib=None)

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
        assert org_1_report["dwh_tables_storage_in_s3_in_mib"] == 5.0

        assert org_1_report["teams"]["3"]["dwh_tables_storage_in_s3_in_mib"] == 5.0
        assert org_1_report["teams"]["3"]["dwh_total_storage_in_s3_in_mib"] == 5.0
        assert org_1_report["teams"]["3"]["dwh_mat_views_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_tables_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_total_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_mat_views_storage_in_s3_in_mib"] == 0

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["dwh_tables_storage_in_s3_in_mib"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_data_in_s3_response_with_no_source_tables(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        for _ in range(5):
            DataWarehouseTable.objects.create(
                team_id=3,
                size_in_s3_mib=1,
                external_data_source_id=None,
            )

        DataWarehouseTable.objects.create(team_id=3, size_in_s3_mib=10, deleted=True)
        DataWarehouseTable.objects.create(team_id=3, size_in_s3_mib=None)

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
        assert org_1_report["dwh_tables_storage_in_s3_in_mib"] == 0

        assert org_1_report["teams"]["3"]["dwh_tables_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["3"]["dwh_total_storage_in_s3_in_mib"] == 5.0
        assert org_1_report["teams"]["3"]["dwh_mat_views_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_tables_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_total_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_mat_views_storage_in_s3_in_mib"] == 0

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["dwh_tables_storage_in_s3_in_mib"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_data_in_s3_response_with_mat_views(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        for i in range(5):
            table = DataWarehouseTable.objects.create(
                team_id=3,
                size_in_s3_mib=1,
            )
            DataWarehouseSavedQuery.objects.create(
                team_id=3, name=f"{i}_view", table=table, deleted=False, status=DataWarehouseSavedQuery.Status.COMPLETED
            )

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
        assert org_1_report["dwh_mat_views_storage_in_s3_in_mib"] == 5.0

        assert org_1_report["teams"]["3"]["dwh_mat_views_storage_in_s3_in_mib"] == 5.0
        assert org_1_report["teams"]["3"]["dwh_total_storage_in_s3_in_mib"] == 5.0
        assert org_1_report["teams"]["4"]["dwh_mat_views_storage_in_s3_in_mib"] == 0
        assert org_1_report["teams"]["4"]["dwh_total_storage_in_s3_in_mib"] == 0

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["dwh_mat_views_storage_in_s3_in_mib"] == 0


@freeze_time("2022-01-10T00:01:00Z")
class TestHogFunctionUsageReports(ClickhouseDestroyTablesMixin, TestCase, ClickhouseTestMixin):
    def setUp(self) -> None:
        Team.objects.all().delete()
        run_clickhouse_statement_in_parallel([TRUNCATE_APP_METRICS2_TABLE_SQL])
        return super().setUp()

    def _setup_teams(self) -> None:
        self.org_1 = Organization.objects.create(name="Org 1")
        self.org_1_team_1 = Team.objects.create(pk=3, organization=self.org_1, name="Team 1 org 1")
        self.org_1_team_2 = Team.objects.create(pk=4, organization=self.org_1, name="Team 2 org 1")
        materialize("events", "$exception_values")

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_hog_function_usage_metrics(self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock) -> None:
        self._setup_teams()

        create_app_metric2(team_id=self.org_1_team_1.id, app_source="hog_function", metric_name="succeeded", count=2)
        create_app_metric2(team_id=self.org_1_team_2.id, app_source="hog_function", metric_name="failed", count=3)
        create_app_metric2(team_id=self.org_1_team_1.id, app_source="hog_function", metric_name="fetch", count=1)
        create_app_metric2(team_id=self.org_1_team_2.id, app_source="hog_function", metric_name="fetch", count=2)
        create_app_metric2(
            team_id=self.org_1_team_1.id, app_source="hog_function", metric_name="billable_invocation", count=5
        )
        create_app_metric2(
            team_id=self.org_1_team_2.id, app_source="hog_function", metric_name="billable_invocation", count=3
        )

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["hog_function_calls_in_period"] == 5
        assert org_1_report["hog_function_fetch_calls_in_period"] == 3
        assert org_1_report["cdp_billable_invocations_in_period"] == 8
        assert org_1_report["teams"]["3"]["hog_function_calls_in_period"] == 2
        assert org_1_report["teams"]["3"]["hog_function_fetch_calls_in_period"] == 1
        assert org_1_report["teams"]["3"]["cdp_billable_invocations_in_period"] == 5
        assert org_1_report["teams"]["4"]["hog_function_calls_in_period"] == 3
        assert org_1_report["teams"]["4"]["hog_function_fetch_calls_in_period"] == 2
        assert org_1_report["teams"]["4"]["cdp_billable_invocations_in_period"] == 3


@freeze_time("2022-01-10T10:00:00Z")
class TestErrorTrackingUsageReport(ClickhouseDestroyTablesMixin, TestCase, ClickhouseTestMixin):
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
        materialize("events", "$exception_values")

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_posthog_exceptions_captured_response(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        for i in range(10):
            _create_event(
                distinct_id="3",
                event="$exception",
                timestamp=now() - relativedelta(hours=i),
                team=self.analytics_team,
            )

        for i in range(5):
            _create_event(
                distinct_id="4",
                event="$exception",
                timestamp=now() - relativedelta(hours=i),
                team=self.org_1_team_1,
            )
            _create_event(
                distinct_id="4",
                event="$exception",
                timestamp=now() - relativedelta(hours=i),
                team=self.org_1_team_2,
            )

        for i in range(7):
            _create_event(
                distinct_id="5",
                event="$exception",
                timestamp=now() - relativedelta(hours=i),
                team=self.org_2_team_3,
            )

        # not captured because it was a bug in our own SDK
        _create_event(
            distinct_id="4",
            event="$exception",
            properties={"$exception_values": ["persistence.isDisabled is not a function"]},
            timestamp=now() - relativedelta(hours=1),
            team=self.org_1_team_1,
        )

        # some out of range events
        _create_event(
            distinct_id="3",
            event="$exception",
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
        assert org_1_report["exceptions_captured_in_period"] == 10
        assert org_1_report["teams"][str(self.org_1_team_1.pk)]["exceptions_captured_in_period"] == 5
        assert org_1_report["teams"][str(self.org_1_team_2.pk)]["exceptions_captured_in_period"] == 5

        org_2_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_2.id)], get_instance_metadata(period))
        )

        assert org_2_report["organization_name"] == "Org 2"
        assert org_2_report["exceptions_captured_in_period"] == 7
        assert org_2_report["teams"][str(self.org_2_team_3.pk)]["exceptions_captured_in_period"] == 7


@freeze_time("2022-01-10T10:00:00Z")
class TestAIEventsUsageReport(ClickhouseDestroyTablesMixin, TestCase, ClickhouseTestMixin):
    def setUp(self) -> None:
        Team.objects.all().delete()
        return super().setUp()

    def _setup_teams(self) -> None:
        self.org_1 = Organization.objects.create(name="Org 1")
        self.org_1_team_1 = Team.objects.create(pk=3, organization=self.org_1, name="Team 1 org 1")
        materialize("events", "$exception_values")

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("posthog.tasks.usage_report.send_report_to_billing_service")
    def test_llm_observability_usage_metrics(
        self, billing_task_mock: MagicMock, posthog_capture_mock: MagicMock
    ) -> None:
        self._setup_teams()

        # Create AI Generation events in period
        for i in range(5):
            _create_event(
                distinct_id="test_id",
                event="$ai_generation",
                properties={
                    "$ai_trace_id": "some_id",
                    "$ai_model": "gpt-4o",
                    "$ai_provider": "openai",
                    "$ai_input_tokens": 100,
                    "$ai_output_tokens": 100,
                    "$ai_input_cost_usd": 0.01,
                    "$ai_output_cost_usd": 0.01,
                    "$ai_total_cost_usd": 0.02,
                },
                timestamp=now() - relativedelta(hours=i),
                team=self.org_1_team_1,
            )

        # Create AI Span And Trace events in period
        _create_event(
            distinct_id="test_id",
            event="$ai_span",
            properties={
                "$ai_trace_id": "some_id",
                "$ai_span_id": "some_id",
            },
            timestamp=now() - relativedelta(hours=1),
            team=self.org_1_team_1,
        )

        _create_event(
            distinct_id="test_id",
            event="$ai_trace",
            properties={
                "$ai_trace_id": "some_id",
            },
            timestamp=now() - relativedelta(hours=1),
            team=self.org_1_team_1,
        )

        # Create some out of period events that shouldn't be counted
        _create_event(
            distinct_id="test_id",
            event="$ai_generation",
            properties={
                "$ai_trace_id": "some_id",
                "$ai_model": "gpt-4o",
                "$ai_provider": "openai",
                "$ai_input_tokens": 100,
                "$ai_output_tokens": 100,
                "$ai_input_cost_usd": 0.01,
                "$ai_output_cost_usd": 0.01,
                "$ai_total_cost_usd": 0.02,
            },
            timestamp=now() - relativedelta(days=2),
            team=self.org_1_team_1,
        )

        # Create some non-AI events that shouldn't be counted
        _create_event(
            distinct_id="test_id",
            event="$pageview",
            timestamp=now() - relativedelta(hours=1),
            team=self.org_1_team_1,
        )

        flush_persons_and_events()

        period = get_previous_day(at=now() + relativedelta(days=1))
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        org_1_report = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.org_1.id)], get_instance_metadata(period))
        )

        assert org_1_report["organization_name"] == "Org 1"
        assert org_1_report["ai_event_count_in_period"] == 7
        assert org_1_report["teams"]["3"]["ai_event_count_in_period"] == 7


class TestSendUsage(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
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
            event="$exception",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
            properties={"$exception_issue_id": "should_not_be_counted"},
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
        materialize("events", "$exception_values")

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
                    "feature_flag_requests": {
                        "usage": 1000,
                        "limit": None,
                    },
                    "api_queries_read_bytes": {
                        "usage": 1024,
                        "limit": None,
                    },
                },
            }
        }

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_send_usage(self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock) -> None:
        mockresponse = Mock()
        mockresponse.status_code = 200
        mockresponse.json = lambda: self._usage_report_response()
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        mock_producer = MagicMock()
        mock_get_sqs_producer.return_value = mock_producer

        period = get_previous_day()
        period_start, period_end = period
        all_reports = _get_all_org_reports(period_start, period_end)

        full_report_as_dict = _get_full_org_usage_report_as_dict(
            _get_full_org_usage_report(all_reports[str(self.organization.id)], get_instance_metadata(period))
        )
        json_data = json.dumps(
            {"organization_id": str(self.organization.id), "usage_report": full_report_as_dict}, separators=(",", ":")
        )
        compressed_bytes = gzip.compress(json_data.encode("utf-8"))
        compressed_b64 = base64.b64encode(compressed_bytes).decode("ascii")

        send_all_org_usage_reports(dry_run=False)
        license = License.objects.first()
        assert license

        mock_producer.send_message.assert_called_once_with(
            message_attributes={
                "content_encoding": "gzip",
                "content_type": "application/json",
            },
            message_body=compressed_b64,
        )

        # mock_posthog.capture.assert_any_call(
        #     get_machine_id(),
        #     "organization usage report",
        #     {**full_report_as_dict, "scope": "machine"},
        #     groups={"instance": ANY},
        #     timestamp=None,
        # )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_send_usage_cloud(self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock) -> None:
        with self.is_cloud(True):
            mockresponse = Mock()
            mockresponse.status_code = 200
            mockresponse.json = lambda: self._usage_report_response()
            mock_posthog = MagicMock()
            mock_client.return_value = mock_posthog

            mock_producer = MagicMock()
            mock_get_sqs_producer.return_value = mock_producer

            period = get_previous_day()
            period_start, period_end = period
            all_reports = _get_all_org_reports(period_start, period_end)

            full_report_as_dict = _get_full_org_usage_report_as_dict(
                _get_full_org_usage_report(all_reports[str(self.organization.id)], get_instance_metadata(period))
            )
            json_data = json.dumps(
                {"organization_id": str(self.organization.id), "usage_report": full_report_as_dict},
                separators=(",", ":"),
            )
            compressed_bytes = gzip.compress(json_data.encode("utf-8"))
            compressed_b64 = base64.b64encode(compressed_bytes).decode("ascii")

            send_all_org_usage_reports(dry_run=False)
            license = License.objects.first()
            assert license

            mock_producer.send_message.assert_called_once_with(
                message_attributes={
                    "content_encoding": "gzip",
                    "content_type": "application/json",
                },
                message_body=compressed_b64,
            )

            # mock_posthog.capture.assert_any_call(
            #     self.user.distinct_id,
            #     "organization usage report",
            #     {**full_report_as_dict, "scope": "user"},
            #     groups={
            #         "instance": "http://localhost:8010",
            #         "organization": str(self.organization.id),
            #     },
            #     timestamp=None,
            # )

    # @freeze_time("2021-10-10T23:01:00Z")
    # @patch("posthog.tasks.usage_report.sync_execute", side_effect=Exception())
    # @patch("posthog.tasks.usage_report.get_ph_client")
    # @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    # def test_send_usage_cloud_exception(
    #     self,
    #     mock_get_sqs_producer: MagicMock,
    #     mock_client: MagicMock,
    #     mock_sync_execute: MagicMock,
    #     mock_capture_exception: MagicMock,
    # ) -> None:
    #     with pytest.raises(Exception):
    #         with self.is_cloud(True):
    #             mockresponse = Mock()
    #             mock_get_sqs_producer.return_value = MagicMock()
    #             mockresponse.status_code = 200
    #             mockresponse.json = lambda: self._usage_report_response()
    #             mock_posthog = MagicMock()
    #             mock_client.return_value = mock_posthog
    #             send_all_org_usage_reports(dry_run=False)
    #     assert mock_capture_exception.call_count == 1

    @patch("posthog.tasks.usage_report.get_ph_client")
    def test_capture_event_called_with_string_timestamp(self, mock_client: MagicMock) -> None:
        organization = Organization.objects.create()
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog
        capture_event(
            pha_client=mock_client,
            name="test event",
            organization_id=organization.id,
            properties={"prop1": "val1"},
            timestamp="2021-10-10T23:01:00.00Z",
        )
        assert mock_client.capture.call_args[1]["timestamp"] == datetime(2021, 10, 10, 23, 1, tzinfo=tzutc())


class TestSendNoUsage(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        materialize("events", "$exception_values")

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("requests.post")
    def test_usage_not_sent_if_zero(self, mock_post: MagicMock, mock_client: MagicMock) -> None:
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog

        send_all_org_usage_reports(dry_run=False)

        mock_post.assert_not_called()


class TestSendUsageNoLicense(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        materialize("events", "$exception_values")

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthog.tasks.usage_report.get_ph_client")
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

    def test_get_teams_for_usage_reports_only_fields(self) -> None:
        teams = _get_teams_for_usage_reports()
        team: Team = teams[0]

        # these fields are included in the query, so shouldn't require additional queries
        with self.assertNumQueries(0):
            _ = team.id
            _ = team.organization.id
            _ = team.organization.name
            _ = team.organization.created_at

        # This field is not included in the original team query, so should require an additional query
        with self.assertNumQueries(1):
            _ = team.organization.for_internal_metrics


@freeze_time("2021-10-10T23:01:00Z")
class TestOrganizationFiltering(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
    """Test organization_ids filtering for send_all_org_usage_reports"""

    def setUp(self) -> None:
        super().setUp()

        # Create additional organizations with teams
        self.org2 = Organization.objects.create(name="Org 2")
        self.team2 = Team.objects.create(organization=self.org2)

        self.org3 = Organization.objects.create(name="Org 3")
        self.team3 = Team.objects.create(organization=self.org3)

        # Create events for all orgs
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team2,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team3,
            distinct_id=1,
            timestamp="2021-10-09T16:01:01Z",
        )
        flush_persons_and_events()
        TEST_clear_instance_license_cache()
        materialize("events", "$exception_values")

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_filter_to_single_organization(self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock) -> None:
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog
        mock_producer = MagicMock()
        mock_get_sqs_producer.return_value = mock_producer

        send_all_org_usage_reports(dry_run=False, organization_ids=[str(self.organization.id)])

        # Should only send one message (for org1)
        assert mock_producer.send_message.call_count == 1

        # Verify the sent org ID
        call_args = mock_producer.send_message.call_args
        message_body = call_args.kwargs["message_body"]
        decompressed = gzip.decompress(base64.b64decode(message_body))
        data = json.loads(decompressed)

        assert data["organization_id"] == str(self.organization.id)
        assert data["usage_report"]["organization_id"] == str(self.organization.id)

        capture_calls = [
            call for call in mock_posthog.capture.call_args_list if call[1].get("event") == "usage reports complete"
        ]
        assert len(capture_calls) == 1
        properties = capture_calls[0][1]["properties"]
        assert properties["filtered"] is True
        assert properties["requested_org_count"] == 1
        assert properties["total_orgs"] == 1
        assert properties.get("requested_missing_org_count") is None

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_filter_to_multiple_organizations(self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock) -> None:
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog
        mock_producer = MagicMock()
        mock_get_sqs_producer.return_value = mock_producer

        org_ids = [str(self.organization.id), str(self.org2.id)]
        send_all_org_usage_reports(dry_run=False, organization_ids=org_ids)

        # Should send two messages
        assert mock_producer.send_message.call_count == 2

        # Verify both org IDs were sent
        sent_org_ids = []
        for call in mock_producer.send_message.call_args_list:
            message_body = call.kwargs["message_body"]
            decompressed = gzip.decompress(base64.b64decode(message_body))
            data = json.loads(decompressed)
            sent_org_ids.append(data["organization_id"])

        assert set(sent_org_ids) == set(org_ids)

        capture_calls = [
            call for call in mock_posthog.capture.call_args_list if call[1].get("event") == "usage reports complete"
        ]
        properties = capture_calls[0][1]["properties"]
        assert properties["filtered"] is True
        assert properties["requested_org_count"] == 2
        assert properties["total_orgs"] == 2
        assert properties.get("requested_missing_org_count") is None

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_filter_with_missing_organization(self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock) -> None:
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog
        mock_producer = MagicMock()
        mock_get_sqs_producer.return_value = mock_producer

        fake_org_id = str(uuid4())

        send_all_org_usage_reports(dry_run=False, organization_ids=[fake_org_id])

        # Should not send any messages
        mock_producer.send_message.assert_not_called()

        capture_calls = [
            call for call in mock_posthog.capture.call_args_list if call[1].get("event") == "usage reports complete"
        ]
        assert len(capture_calls) == 1
        properties = capture_calls[0][1]["properties"]
        assert properties["filtered"] is True
        assert properties["requested_org_count"] == 1
        assert properties["requested_missing_org_count"] == 1
        assert properties["total_orgs"] == 0

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_filter_with_mix_of_found_and_missing(
        self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog
        mock_producer = MagicMock()
        mock_get_sqs_producer.return_value = mock_producer

        fake_org_id1 = str(uuid4())
        fake_org_id2 = str(uuid4())
        org_ids = [str(self.organization.id), fake_org_id1, str(self.org2.id), fake_org_id2]

        send_all_org_usage_reports(dry_run=False, organization_ids=org_ids)

        # Should send two messages (for the 2 existing orgs)
        assert mock_producer.send_message.call_count == 2

        # Verify correct org IDs were sent
        sent_org_ids = []
        for call in mock_producer.send_message.call_args_list:
            message_body = call.kwargs["message_body"]
            decompressed = gzip.decompress(base64.b64decode(message_body))
            data = json.loads(decompressed)
            sent_org_ids.append(data["organization_id"])

        assert set(sent_org_ids) == {str(self.organization.id), str(self.org2.id)}

        capture_calls = [
            call for call in mock_posthog.capture.call_args_list if call[1].get("event") == "usage reports complete"
        ]
        properties = capture_calls[0][1]["properties"]
        assert properties["filtered"] is True
        assert properties["requested_org_count"] == 4
        assert properties["requested_missing_org_count"] == 2
        assert properties["total_orgs"] == 2

    @patch("posthog.tasks.usage_report.get_ph_client")
    @patch("products.enterprise.backend.sqs.SQSProducer.get_sqs_producer")
    def test_no_filter_processes_all_organizations(
        self, mock_get_sqs_producer: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_posthog = MagicMock()
        mock_client.return_value = mock_posthog
        mock_producer = MagicMock()
        mock_get_sqs_producer.return_value = mock_producer

        send_all_org_usage_reports(dry_run=False)

        # Should send three messages (one for each org)
        assert mock_producer.send_message.call_count == 3

        # Verify telemetry shows unfiltered
        capture_calls = [
            call for call in mock_posthog.capture.call_args_list if call[1].get("event") == "usage reports complete"
        ]
        properties = capture_calls[0][1]["properties"]
        assert properties["filtered"] is False
        assert properties.get("requested_org_count") is None
        assert properties.get("requested_missing_org_count") is None
        assert properties["total_orgs"] == 3


class TestQuerySplitting(ClickhouseDestroyTablesMixin, ClickhouseTestMixin, TestCase):
    def setUp(self) -> None:
        super().setUp()
        materialize("events", "$exception_values")

        # Clear existing Django data
        Team.objects.all().delete()
        Organization.objects.all().delete()

        # Create a fresh team for testing
        self.team = Team.objects.create(organization=Organization.objects.create(name="test"))
        # Create test events across a time period
        self.begin = datetime(2023, 1, 1, 0, 0)
        self.end = datetime(2023, 1, 2, 0, 0)

        # Create 10 events in the time period
        for i in range(10):
            _create_event(
                event="test_event",
                team=self.team,
                distinct_id=f"user_{i}",
                timestamp=self.begin + relativedelta(hours=i),
                properties={},
                person_mode="propertyless",
            )

        # Create some events with person_mode for enhanced persons test
        for i in range(5):
            _create_event(
                event="enhanced_event",
                team=self.team,
                distinct_id=f"enhanced_user_{i}",
                timestamp=self.begin + relativedelta(hours=i),
                properties={"$lib": "web"},
                person_mode="full",
            )

        # Create survey sent and feature flag called events
        for i in range(3):
            _create_event(
                event="survey sent",
                team=self.team,
                distinct_id=f"survey_user_{i}",
                timestamp=self.begin + relativedelta(hours=i),
                properties={"survey_id": f"survey_{i}"},
                person_mode="full",
            )

        for i in range(3):
            _create_event(
                event="$feature_flag_called",
                team=self.team,
                distinct_id=f"ff_user_{i}",
                timestamp=self.begin + relativedelta(hours=i),
                properties={"$feature_flag": f"flag_{i}"},
                person_mode="full",
            )

        # Create various types of AI events that should NOT be counted in billable events
        # $ai_generation events
        for i in range(3):
            _create_event(
                event="$ai_generation",
                team=self.team,
                distinct_id=f"ai_gen_user_{i}",
                timestamp=self.begin + relativedelta(hours=i),
                properties={
                    "$ai_model": "gpt-4",
                    "$ai_provider": "openai",
                    "$ai_input_tokens": 100,
                    "$ai_output_tokens": 50,
                },
                person_mode="full",
            )

        # $ai_span events
        for i in range(2):
            _create_event(
                event="$ai_span",
                team=self.team,
                distinct_id=f"ai_span_user_{i}",
                timestamp=self.begin + relativedelta(hours=i),
                properties={
                    "$ai_trace_id": f"trace_{i}",
                    "$ai_span_id": f"span_{i}",
                },
                person_mode="full",
            )

        # $ai_trace events
        _create_event(
            event="$ai_trace",
            team=self.team,
            distinct_id="ai_trace_user",
            timestamp=self.begin + relativedelta(hours=1),
            properties={
                "$ai_trace_id": "trace_1",
            },
            person_mode="full",
        )

        # $ai_embedding events
        for i in range(2):
            _create_event(
                event="$ai_embedding",
                team=self.team,
                distinct_id=f"ai_embed_user_{i}",
                timestamp=self.begin + relativedelta(hours=i),
                properties={
                    "$ai_model": "text-embedding-ada-002",
                    "$ai_provider": "openai",
                    "$ai_input_tokens": 50,
                },
                person_mode="full",
            )

        # $ai_feedback events
        _create_event(
            event="$ai_feedback",
            team=self.team,
            distinct_id="ai_feedback_user",
            timestamp=self.begin + relativedelta(hours=2),
            properties={
                "$ai_trace_id": "trace_1",
                "rating": 5,
            },
            person_mode="full",
        )

        # $ai_metric events
        _create_event(
            event="$ai_metric",
            team=self.team,
            distinct_id="ai_metric_user",
            timestamp=self.begin + relativedelta(hours=3),
            properties={
                "$ai_trace_id": "trace_1",
                "latency_ms": 250,
            },
            person_mode="full",
        )

        flush_persons_and_events()

    @patch("posthog.tasks.usage_report.sync_execute")
    def test_execute_split_query_splits_correctly(self, mock_sync_execute: MagicMock) -> None:
        """Test that _execute_split_query correctly splits the time period and combines results."""
        # Mock the sync_execute to return test data
        mock_sync_execute.side_effect = [
            [(self.team.id, 5)],  # First split returns 5 events
            [(self.team.id, 5)],  # Second split returns 5 events
        ]

        # Test with 2 splits
        query_template = """
            SELECT team_id, count(1) as count
            FROM events
            WHERE timestamp BETWEEN %(begin)s AND %(end)s
            GROUP BY team_id
        """

        from posthog.tasks.usage_report import _execute_split_query

        result = _execute_split_query(
            begin=self.begin, end=self.end, query_template=query_template, params={}, num_splits=2
        )

        # Verify sync_execute was called twice with different time ranges
        self.assertEqual(mock_sync_execute.call_count, 2)

        # First call should use the first half of the time range
        first_call_args = mock_sync_execute.call_args_list[0][0]
        self.assertEqual(first_call_args[1]["begin"], self.begin)
        mid_point = self.begin + (self.end - self.begin) / 2
        self.assertEqual(first_call_args[1]["end"], mid_point)

        # Second call should use the second half of the time range
        second_call_args = mock_sync_execute.call_args_list[1][0]
        self.assertEqual(second_call_args[1]["begin"], mid_point)
        self.assertEqual(second_call_args[1]["end"], self.end)

        # Result should combine both splits (5 + 5 = 10)
        self.assertEqual(result, [(self.team.id, 10)])

    @patch("posthog.tasks.usage_report.sync_execute")
    def test_execute_split_query_with_custom_combiner(self, mock_sync_execute: MagicMock) -> None:
        """Test that _execute_split_query works with a custom result combiner function."""
        # Mock the sync_execute to return test data for event metrics
        mock_sync_execute.side_effect = [
            [(self.team.id, "web_events", 3)],  # First split
            [(self.team.id, "web_events", 2), (self.team.id, "mobile_events", 1)],  # Second split
        ]

        # Define a custom combiner function similar to what we use in get_all_event_metrics_in_period
        def custom_combiner(results_list: list) -> dict[str, list[tuple[int, int]]]:
            metrics: dict[str, dict[int, int]] = {
                "web_events": {},
                "mobile_events": {},
            }

            for results in results_list:
                for team_id, metric, count in results:
                    if team_id in metrics[metric]:
                        metrics[metric][team_id] += count
                    else:
                        metrics[metric][team_id] = count

            return {metric: list(team_counts.items()) for metric, team_counts in metrics.items()}

        query_template = """
            SELECT team_id, 'web_events' as metric, count(1) as count
            FROM events
            WHERE timestamp BETWEEN %(begin)s AND %(end)s
            GROUP BY team_id, metric
        """

        from posthog.tasks.usage_report import _execute_split_query

        result = _execute_split_query(
            begin=self.begin,
            end=self.end,
            query_template=query_template,
            params={},
            num_splits=2,
            combine_results_func=custom_combiner,
        )

        # Verify the custom combiner worked correctly
        self.assertEqual(result["web_events"], [(self.team.id, 5)])
        self.assertEqual(result["mobile_events"], [(self.team.id, 1)])

    def test_get_teams_with_billable_event_count_in_period(self) -> None:
        """Test that get_teams_with_billable_event_count_in_period returns correct results after splitting and excludes AI events."""
        from posthog.tasks.usage_report import get_teams_with_billable_event_count_in_period

        # Run the function with our test data
        result = get_teams_with_billable_event_count_in_period(self.begin, self.end)

        # We should get 15 events for our team (10 test_event + 5 enhanced_event)
        # NOT counting: 3 survey sent, 3 $feature_flag_called, 10 AI events
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], self.team.id)
        self.assertEqual(result[0][1], 15)

        # Test with count_distinct=True
        result_distinct = get_teams_with_billable_event_count_in_period(self.begin, self.end, count_distinct=True)
        self.assertEqual(len(result_distinct), 1)
        self.assertEqual(result_distinct[0][0], self.team.id)
        # Should still be 15 since we created 15 distinct billable events (excluding AI events)
        self.assertEqual(result_distinct[0][1], 15)

    def test_get_teams_with_billable_enhanced_persons_event_count_in_period(self) -> None:
        """Test that get_teams_with_billable_enhanced_persons_event_count_in_period returns correct results after splitting."""
        from posthog.tasks.usage_report import get_teams_with_billable_enhanced_persons_event_count_in_period

        # Run the function with our test data
        result = get_teams_with_billable_enhanced_persons_event_count_in_period(self.begin, self.end)

        # We should get 5 enhanced events for our team
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], self.team.id)
        self.assertEqual(result[0][1], 5)

    @patch("posthog.tasks.usage_report._execute_split_query")
    def test_split_query_with_different_num_splits(self, mock_execute_split_query: MagicMock) -> None:
        """Test that functions call _execute_split_query with the correct number of splits."""
        mock_execute_split_query.return_value = [(self.team.id, 10)]

        from posthog.tasks.usage_report import (
            get_all_event_metrics_in_period,
            get_teams_with_billable_event_count_in_period,
        )

        # Call the functions
        get_teams_with_billable_event_count_in_period(self.begin, self.end)
        get_all_event_metrics_in_period(self.begin, self.end)

        # Verify the calls
        self.assertEqual(mock_execute_split_query.call_count, 2)

        # First call (get_teams_with_billable_event_count_in_period) should use 3 splits
        first_call_kwargs = mock_execute_split_query.call_args_list[0][1]
        self.assertEqual(first_call_kwargs["num_splits"], 3)

        # Second call (get_all_event_metrics_in_period) should use 3 splits
        second_call_kwargs = mock_execute_split_query.call_args_list[1][1]
        self.assertEqual(second_call_kwargs["num_splits"], 3)

    def test_ai_events_not_double_counted(self) -> None:
        """Test that AI events are excluded from billable event counts and counted separately."""
        from posthog.tasks.usage_report import (
            get_teams_with_ai_event_count_in_period,
            get_teams_with_billable_event_count_in_period,
        )

        # First, get the baseline billable count with existing events
        billable_result_before = get_teams_with_billable_event_count_in_period(self.begin, self.end)
        baseline_count = billable_result_before[0][1] if billable_result_before else 0

        # Create additional AI events that should NOT increase billable count
        for i in range(5):
            _create_event(
                event="$ai_generation",
                team=self.team,
                distinct_id=f"new_ai_user_{i}",
                timestamp=self.begin + relativedelta(hours=i + 10),
                properties={"$ai_model": "claude-3", "$ai_provider": "anthropic"},
            )

        flush_persons_and_events()

        # Get counts after adding more AI events
        billable_result_after = get_teams_with_billable_event_count_in_period(self.begin, self.end)
        ai_result = get_teams_with_ai_event_count_in_period(self.begin, self.end)

        # Billable count should NOT have increased
        self.assertEqual(billable_result_after[0][1], baseline_count)

        # AI count should include original 10 + 5 new = 15
        self.assertEqual(ai_result[0][1], 15)

        # Now add a regular event and verify it DOES increase billable count
        _create_event(
            event="regular_event",
            team=self.team,
            distinct_id="regular_user",
            timestamp=self.begin + relativedelta(hours=12),
        )
        flush_persons_and_events()

        billable_result_final = get_teams_with_billable_event_count_in_period(self.begin, self.end)
        self.assertEqual(billable_result_final[0][1], baseline_count + 1)

    def test_integration_with_usage_report(self) -> None:
        """Test that the usage report generation still works with the new query splitting."""
        period_start, period_end = get_previous_day(at=self.end)

        # Create some events in the period
        for i in range(5):
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id=f"user_{i}",
                timestamp=period_start + relativedelta(hours=i),
                properties={},
            )

        flush_persons_and_events()

        # Get the usage data
        all_data = _get_all_usage_data_as_team_rows(period_start, period_end)

        # Verify the data
        self.assertIn("teams_with_event_count_in_period", all_data)
        self.assertEqual(len(all_data["teams_with_event_count_in_period"]), 1)
        self.assertEqual(next(iter(all_data["teams_with_event_count_in_period"].keys())), self.team.id)
        self.assertEqual(all_data["teams_with_event_count_in_period"][self.team.id], 20)
