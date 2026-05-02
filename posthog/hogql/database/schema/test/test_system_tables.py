from posthog.test.base import BaseTest, NonAtomicBaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import (
    Action,
    Annotation,
    Cohort,
    ExportedAsset,
    FeatureFlag,
    Group,
    GroupTypeMapping,
    GroupUsageMetric,
    Insight,
    InsightVariable,
    Organization,
    Team,
)
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.alert import AlertConfiguration
from posthog.models.cohort.calculation_history import CohortCalculationHistory
from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.project import Project

from products.conversations.backend.models import Ticket
from products.dashboards.backend.models.dashboard import Dashboard
from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable as DataWarehouseTableModel
from products.early_access_features.backend.models import EarlyAccessFeature
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSymbolSet
from products.experiments.backend.models.experiment import Experiment
from products.llm_analytics.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.llm_analytics.backend.models.score_definitions import ScoreDefinition
from products.llm_analytics.backend.models.trace_reviews import TraceReview, TraceReviewScore
from products.logs.backend.models import LogsAlertConfiguration, LogsView
from products.notebooks.backend.models import Notebook
from products.surveys.backend.models import Survey

ALL_SYSTEM_TABLE_NAMES = sorted(SystemTables().children.keys())

# {table_name: "sql_alias.column_name"} for team_id filter assertion
TEAM_ID_FILTER_PATTERNS = {
    "ingestion_warnings": "ingestion_warnings.team_id",  # ClickHouse-native table, no system__ prefix
    "teams": "system__teams.id",  # team_id is aliased to id column
}


class TestSystemTablesTeamScoping(BaseTest):
    """Verify every system table's generated SQL includes a team_id WHERE clause."""

    @parameterized.expand(ALL_SYSTEM_TABLE_NAMES)
    def test_system_table_has_team_id_filter(self, table_name):
        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )
        sql = f"SELECT * FROM system.{table_name}"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

        pattern = TEAM_ID_FILTER_PATTERNS.get(table_name, f"system__{table_name}.team_id")
        assert f"equals({pattern}, {self.team.pk})" in query

    def test_all_system_tables_have_isolation_tests(self):
        """Fails when a new system table is added without a corresponding isolation test."""
        all_tables = set(SystemTables().children.keys())
        tested_tables = {name for name, _ in SYSTEM_TABLE_FACTORIES}
        excluded_tables = {
            # ingestion_warnings is a ClickHouse-native table (not backed by PostgreSQL),
            # so it can't be tested with Django model factories.
            "ingestion_warnings",
        }

        untested = all_tables - tested_tables - excluded_tables
        assert not untested, (
            f"System tables missing isolation tests: {sorted(untested)}. "
            f"Add a factory to SYSTEM_TABLE_FACTORIES in test_system_tables.py "
            f"or add to excluded_tables with a reason."
        )

    def test_error_tracking_symbol_sets_does_not_expose_storage_internals(self):
        table = SystemTables().children["error_tracking_symbol_sets"].get()
        assert isinstance(table, Table)

        assert "storage_ptr" not in table.fields
        assert "content_hash" not in table.fields


def _create_batch_export(team: Team, label: str):
    from posthog.batch_exports.models import BatchExport, BatchExportDestination

    destination = BatchExportDestination.objects.create(type="S3", config={})
    return BatchExport.objects.create(team=team, name=f"export_{label}", destination=destination, interval="hour")


def _create_batch_export_backfill(team: Team, label: str):
    from posthog.batch_exports.models import BatchExport, BatchExportBackfill, BatchExportDestination

    destination = BatchExportDestination.objects.create(type="S3", config={})
    batch_export = BatchExport.objects.create(
        team=team, name=f"export_for_backfill_{label}", destination=destination, interval="hour"
    )
    return BatchExportBackfill.objects.create(team=team, batch_export=batch_export, status="Running")


def _create_alert(team: Team, label: str) -> AlertConfiguration:
    insight = Insight.objects.create(team=team, name=f"insight_for_alert_{label}")
    return AlertConfiguration.objects.create(team=team, insight=insight, name=f"alert_{label}")


def _create_activity_log(team: Team, label: str) -> ActivityLog:
    return ActivityLog.objects.create(team_id=team.pk, activity="updated", scope="FeatureFlag", item_id=label)


def _create_action(team: Team, label: str) -> Action:
    return Action.objects.create(team=team, name=f"action_{label}")


def _create_cohort(team: Team, label: str) -> Cohort:
    return Cohort.objects.create(team=team, name=f"cohort_{label}")


def _create_annotation(team: Team, label: str) -> Annotation:
    return Annotation.objects.create(team=team, content=f"annotation_{label}")


def _create_cohort_calculation_history(team: Team, label: str) -> CohortCalculationHistory:
    cohort = Cohort.objects.create(team=team, name=f"cohort_for_calc_{label}")
    return CohortCalculationHistory.objects.create(team=team, cohort=cohort, filters={})


def _create_dashboard(team: Team, label: str) -> Dashboard:
    return Dashboard.objects.create(team=team, name=f"dashboard_{label}")


def _create_data_modeling_job(team: Team, label: str) -> DataModelingJob:
    saved_query = DataWarehouseSavedQuery.objects.create(
        team=team, name=f"query_{label}", query={"kind": "HogQLQuery", "query": "SELECT 1"}
    )
    return DataModelingJob.objects.create(team=team, saved_query=saved_query)


def _create_data_warehouse_saved_query(team: Team, label: str) -> DataWarehouseSavedQuery:
    return DataWarehouseSavedQuery.objects.create(
        team=team, name=f"view_{label}", query={"kind": "HogQLQuery", "query": "SELECT 1"}
    )


def _create_data_warehouse_source(team: Team, label: str) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=f"source_{label}",
        connection_id=f"conn_{label}",
        status="Running",
        source_type="Stripe",
    )


def _create_data_warehouse_table(team: Team, label: str) -> DataWarehouseTableModel:
    return DataWarehouseTableModel.raw_objects.create(
        team=team, name=f"table_{label}", format="CSV", url_pattern="s3://bucket/path", columns={}
    )


def _create_source_sync_job(team: Team, label: str) -> ExternalDataJob:
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=f"source_for_job_{label}",
        connection_id=f"conn_for_job_{label}",
        status="Running",
        source_type="Stripe",
    )
    return ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        status="Completed",
        rows_synced=100,
    )


def _create_source_schema(team: Team, label: str) -> ExternalDataSchema:
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=f"source_for_schema_{label}",
        connection_id=f"conn_for_schema_{label}",
        status="Running",
        source_type="Stripe",
    )
    return ExternalDataSchema.objects.create(
        team=team,
        source=source,
        name=f"schema_{label}",
        should_sync=True,
        status="Completed",
    )


def _create_early_access_feature(team: Team, label: str) -> EarlyAccessFeature:
    flag = FeatureFlag.objects.create(team=team, key=f"eaf_flag_{label}")
    return EarlyAccessFeature.objects.create(team=team, name=f"eaf_{label}", stage="draft", feature_flag=flag)


def _get_or_create_user_for_team(team: Team, label: str):
    from posthog.models.user import User

    user = User.objects.filter(organization_membership__organization=team.organization).first()
    if not user:
        user = User.objects.create(email=f"test_{label}@posthog.com")
    return user


def _create_endpoint(team: Team, label: str) -> Endpoint:
    user = _get_or_create_user_for_team(team, label)
    return Endpoint.objects.create(team=team, name=f"ep_{label}", created_by=user)


def _create_endpoint_version(team: Team, label: str) -> EndpointVersion:
    user = _get_or_create_user_for_team(team, label)
    endpoint = Endpoint.objects.create(team=team, name=f"ep_for_ver_{label}", created_by=user)
    return EndpointVersion.objects.create(
        endpoint=endpoint,
        team=team,
        version=1,
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
        created_by=user,
    )


def _create_error_tracking_issue(team: Team, label: str) -> ErrorTrackingIssue:
    return ErrorTrackingIssue.objects.create(team=team, name=f"issue_{label}", status="active")


def _create_error_tracking_issue_assignment(team: Team, label: str):
    from products.error_tracking.backend.models import ErrorTrackingIssueAssignment

    issue = ErrorTrackingIssue.objects.create(team=team, name=f"assigned_issue_{label}", status="active")
    return ErrorTrackingIssueAssignment.objects.create(team=team, issue=issue)


def _create_error_tracking_issue_fingerprint(team: Team, label: str):
    from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2

    issue = ErrorTrackingIssue.objects.create(team=team, name=f"fp_issue_{label}", status="active")
    return ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=f"fp_{label}")


def _create_error_tracking_assignment_rule(team: Team, label: str):
    from products.error_tracking.backend.models import ErrorTrackingAssignmentRule

    return ErrorTrackingAssignmentRule.objects.create(
        team=team, filters={"type": "AND", "values": []}, bytecode=[], order_key=0
    )


def _create_error_tracking_suppression_rule(team: Team, label: str):
    from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

    return ErrorTrackingSuppressionRule.objects.create(
        team=team, filters={"type": "AND", "values": []}, bytecode=[], order_key=0, sampling_rate=1.0
    )


def _create_error_tracking_release(team: Team, label: str):
    from products.error_tracking.backend.models import ErrorTrackingRelease

    return ErrorTrackingRelease.objects.create(
        team=team, hash_id=f"hash_{label}", version=f"v_{label}", project=f"proj_{label}"
    )


def _create_error_tracking_symbol_set(team: Team, label: str) -> ErrorTrackingSymbolSet:
    return ErrorTrackingSymbolSet.objects.create(
        team=team, ref=f"symbol_set_{label}", storage_ptr=f"symbolsets/{label}"
    )


def _create_hog_flow(team: Team, label: str) -> HogFlow:
    return HogFlow.objects.create(team=team, name=f"flow_{label}")


def _create_hog_function(team: Team, label: str) -> HogFunction:
    return HogFunction.objects.create(
        team=team,
        name=f"function_{label}",
        type="destination",
        hog="return true",
        enabled=True,
    )


def _create_experiment(team: Team, label: str) -> Experiment:
    flag = FeatureFlag.objects.create(team=team, key=f"flag_for_exp_{label}")
    return Experiment.objects.create(team=team, name=f"experiment_{label}", feature_flag=flag)


def _create_export(team: Team, label: str) -> ExportedAsset:
    return ExportedAsset.objects.create(team=team, export_format="text/csv")


def _create_feature_flag(team: Team, label: str) -> FeatureFlag:
    return FeatureFlag.objects.create(team=team, key=f"flag_{label}")


def _create_group(team: Team, label: str) -> Group:
    return Group.objects.create(team=team, group_key=f"group_{label}", group_type_index=0, version=0)


def _create_group_type_mapping(team: Team, label: str) -> GroupTypeMapping:
    return GroupTypeMapping.objects.create(
        team=team, project=team.project, group_type=f"type_{label}", group_type_index=0
    )


def _create_integration(team: Team, label: str):
    from posthog.models.integration import Integration

    return Integration.objects.create(team=team, kind="slack", errors="")


def _create_integration_repository_cache_entry(team: Team, label: str):
    from posthog.models.integration import Integration
    from posthog.models.integration_repository_cache import IntegrationRepositoryCacheEntry

    integration = Integration.objects.create(team=team, kind="github", errors="")
    return IntegrationRepositoryCacheEntry.objects.create(
        integration=integration,
        team=team,
        full_name=f"owner/repo_{label}",
        default_branch="main",
        default_branch_sha=f"sha_{label}",
    )


def _create_logs_view(team: Team, label: str) -> LogsView:
    return LogsView.objects.create(team=team, name=f"logs_view_{label}")


def _create_logs_alert(team: Team, label: str) -> LogsAlertConfiguration:
    return LogsAlertConfiguration.objects.create(
        team=team,
        name=f"logs_alert_{label}",
        threshold_count=10,
    )


def _create_review_queue(team: Team, label: str) -> ReviewQueue:
    user = _get_or_create_user_for_team(team, label)
    return ReviewQueue.objects.create(team=team, name=f"review_queue_{label}", created_by=user)


def _create_review_queue_item(team: Team, label: str) -> ReviewQueueItem:
    user = _get_or_create_user_for_team(team, label)
    queue = ReviewQueue.objects.create(team=team, name=f"review_queue_for_item_{label}", created_by=user)
    return ReviewQueueItem.objects.create(team=team, queue=queue, trace_id=f"trace_{label}", created_by=user)


def _create_trace_review(team: Team, label: str) -> TraceReview:
    user = _get_or_create_user_for_team(team, label)
    return TraceReview.objects.create(
        team=team,
        trace_id=f"trace_review_{label}",
        created_by=user,
        reviewed_by=user,
    )


def _create_trace_review_score(team: Team, label: str) -> TraceReviewScore:
    user = _get_or_create_user_for_team(team, label)
    review = TraceReview.objects.create(
        team=team,
        trace_id=f"trace_review_for_score_{label}",
        created_by=user,
        reviewed_by=user,
    )
    definition = ScoreDefinition.objects.create(
        team=team,
        name=f"score_definition_{label}",
        description="",
        kind=ScoreDefinition.Kind.BOOLEAN,
        created_by=user,
    )
    version = definition.create_new_version(
        config={"true_label": "Yes", "false_label": "No"},
        created_by=user,
    )

    return TraceReviewScore.objects.create(
        team=team,
        review=review,
        definition=definition,
        definition_version=version.id,
        definition_version_number=version.version,
        definition_config=version.config,
        boolean_value=True,
        created_by=user,
    )


def _create_insight(team: Team, label: str) -> Insight:
    return Insight.objects.create(team=team, name=f"insight_{label}")


def _create_insight_variable(team: Team, label: str) -> InsightVariable:
    return InsightVariable.objects.create(team=team, name=f"var_{label}", type="String")


def _create_notebook(team: Team, label: str) -> Notebook:
    return Notebook.objects.create(team=team, title=f"notebook_{label}")


def _create_session_recording(team: Team, label: str):
    from posthog.models import SessionRecording

    return SessionRecording.objects.create(team=team, session_id=f"session_{label}")


def _create_session_recording_playlist(team: Team, label: str):
    from posthog.models import SessionRecordingPlaylist

    return SessionRecordingPlaylist.objects.create(team=team, name=f"playlist_{label}", type="collection")


def _create_support_ticket(team: Team, label: str) -> Ticket:
    return Ticket.objects.create_with_number(
        team=team,
        channel_source="widget",
        widget_session_id=f"session_{label}",
        distinct_id=f"user_{label}",
        status="new",
    )


def _create_survey(team: Team, label: str) -> Survey:
    return Survey.objects.create(team=team, name=f"survey_{label}", type="popover")


def _create_task(team: Team, label: str):
    from products.tasks.backend.models import Task

    return Task.objects.create(
        team=team,
        title=f"task_{label}",
        description="x",
        origin_product=Task.OriginProduct.USER_CREATED,
    )


def _create_task_run(team: Team, label: str):
    from products.tasks.backend.models import Task, TaskRun

    task = Task.objects.create(
        team=team,
        title=f"task_for_run_{label}",
        description="x",
        origin_product=Task.OriginProduct.USER_CREATED,
    )
    return TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.QUEUED)


def _create_sandbox_environment(team: Team, label: str):
    from products.tasks.backend.models import SandboxEnvironment

    # private=False so the row is queryable via HogQL — the privacy predicate
    # excludes private environments. Privacy filtering itself is covered by
    # TestSystemTablesSandboxEnvironmentPrivacy.
    return SandboxEnvironment.objects.create(team=team, name=f"env_{label}", private=False)


def _create_team(team: Team, label: str) -> Team:
    return team


def _create_usage_metric(team: Team, label: str) -> GroupUsageMetric:
    return GroupUsageMetric.objects.create(
        team=team,
        group_type_index=0,
        name=f"metric_{label}",
        filters={"events": []},
    )


SYSTEM_TABLE_FACTORIES = [
    ("activity_logs", _create_activity_log),
    ("actions", _create_action),
    ("alerts", _create_alert),
    ("annotations", _create_annotation),
    ("batch_export_backfills", _create_batch_export_backfill),
    ("batch_exports", _create_batch_export),
    ("cohorts", _create_cohort),
    ("cohort_calculation_history", _create_cohort_calculation_history),
    ("dashboards", _create_dashboard),
    ("data_modeling_jobs", _create_data_modeling_job),
    ("data_modeling_views", _create_data_warehouse_saved_query),
    ("data_warehouse_sources", _create_data_warehouse_source),
    ("data_warehouse_tables", _create_data_warehouse_table),
    ("early_access_features", _create_early_access_feature),
    ("data_modeling_endpoint_versions", _create_endpoint_version),
    ("data_modeling_endpoints", _create_endpoint),
    ("error_tracking_assignment_rules", _create_error_tracking_assignment_rule),
    ("error_tracking_issue_assignments", _create_error_tracking_issue_assignment),
    ("error_tracking_issue_fingerprints", _create_error_tracking_issue_fingerprint),
    ("source_sync_jobs", _create_source_sync_job),
    ("error_tracking_issues", _create_error_tracking_issue),
    ("error_tracking_releases", _create_error_tracking_release),
    ("error_tracking_symbol_sets", _create_error_tracking_symbol_set),
    ("error_tracking_suppression_rules", _create_error_tracking_suppression_rule),
    ("experiments", _create_experiment),
    ("exports", _create_export),
    ("feature_flags", _create_feature_flag),
    ("groups", _create_group),
    ("group_type_mappings", _create_group_type_mapping),
    ("hog_flows", _create_hog_flow),
    ("hog_functions", _create_hog_function),
    ("insights", _create_insight),
    ("insight_variables", _create_insight_variable),
    ("integrations", _create_integration),
    ("integration_repository_cache", _create_integration_repository_cache_entry),
    ("logs_alerts", _create_logs_alert),
    ("logs_views", _create_logs_view),
    ("notebooks", _create_notebook),
    ("review_queue_items", _create_review_queue_item),
    ("review_queues", _create_review_queue),
    ("sandbox_environments", _create_sandbox_environment),
    ("session_recording_playlists", _create_session_recording_playlist),
    ("session_recordings", _create_session_recording),
    ("source_schemas", _create_source_schema),
    ("support_tickets", _create_support_ticket),
    ("surveys", _create_survey),
    ("task_runs", _create_task_run),
    ("tasks", _create_task),
    ("teams", _create_team),
    ("trace_review_scores", _create_trace_review_score),
    ("trace_reviews", _create_trace_review),
    ("usage_metrics", _create_usage_metric),
]


class TestSystemTablesTeamIsolation(NonAtomicBaseTest):
    """Create entities in two teams and query via ClickHouse's postgresql() function
    to verify each team only sees its own data."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        self.other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

    @parameterized.expand(SYSTEM_TABLE_FACTORIES)
    def test_system_table_returns_only_own_team_data(self, table_name, factory):
        obj_team1 = factory(self.team, "team1")
        obj_team2 = factory(self.other_team, "team2")

        response = execute_hogql_query(f"SELECT id FROM system.{table_name}", team=self.team)
        ids = {str(row[0]) for row in response.results}

        assert str(obj_team1.pk) in ids
        assert str(obj_team2.pk) not in ids


class TestSystemTablesSandboxEnvironmentPrivacy(BaseTest):
    """Verify the sandbox_environments system table excludes private and internal environments,
    mirroring the REST API's per-creator visibility filter and internal-use exclusion."""

    def test_generated_sql_includes_private_predicate(self):
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        query, _ = prepare_and_print_ast(
            parse_select("SELECT id FROM system.sandbox_environments"), context, dialect="clickhouse"
        )
        assert "system__sandbox_environments.private" in query
        assert "system__sandbox_environments.internal" in query
        assert f"equals(system__sandbox_environments.team_id, {self.team.pk})" in query


class TestSystemTablesSandboxEnvironmentPrivacyIsolation(NonAtomicBaseTest):
    """End-to-end check that private and internal sandbox environments are never returned via HogQL,
    even within the creator's own team."""

    CLASS_DATA_LEVEL_SETUP = False

    def test_private_environments_excluded(self):
        from products.tasks.backend.models import SandboxEnvironment

        public_env = SandboxEnvironment.objects.create(team=self.team, name="public_env", private=False)
        private_env = SandboxEnvironment.objects.create(team=self.team, name="private_env", private=True)

        response = execute_hogql_query("SELECT id FROM system.sandbox_environments", team=self.team)
        ids = {str(row[0]) for row in response.results}

        assert str(public_env.pk) in ids
        assert str(private_env.pk) not in ids

    def test_internal_environments_excluded(self):
        from products.tasks.backend.models import SandboxEnvironment

        regular_env = SandboxEnvironment.objects.create(
            team=self.team, name="regular_env", private=False, internal=False
        )
        internal_env = SandboxEnvironment.objects.create(
            team=self.team, name="internal_env", private=False, internal=True
        )

        response = execute_hogql_query("SELECT id FROM system.sandbox_environments", team=self.team)
        ids = {str(row[0]) for row in response.results}

        assert str(regular_env.pk) in ids
        assert str(internal_env.pk) not in ids


class TestSystemTablesTaskInternalExclusion(BaseTest):
    """Verify the tasks system table excludes internal tasks (signals pipeline, etc.)
    mirroring the REST API's default filter."""

    def test_generated_sql_includes_internal_predicate(self):
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        query, _ = prepare_and_print_ast(parse_select("SELECT id FROM system.tasks"), context, dialect="clickhouse")
        assert "system__tasks.internal" in query
        assert f"equals(system__tasks.team_id, {self.team.pk})" in query


class TestSystemTablesTaskInternalExclusionIsolation(NonAtomicBaseTest):
    """End-to-end check that internal tasks are never returned via HogQL."""

    CLASS_DATA_LEVEL_SETUP = False

    def test_internal_tasks_excluded(self):
        from products.tasks.backend.models import Task

        regular_task = Task.objects.create(
            team=self.team,
            title="regular",
            description="x",
            origin_product=Task.OriginProduct.USER_CREATED,
            internal=False,
        )
        internal_task = Task.objects.create(
            team=self.team,
            title="internal",
            description="x",
            origin_product=Task.OriginProduct.USER_CREATED,
            internal=True,
        )

        response = execute_hogql_query("SELECT id FROM system.tasks", team=self.team)
        ids = {str(row[0]) for row in response.results}

        assert str(regular_task.pk) in ids
        assert str(internal_task.pk) not in ids
