import uuid
from typing import TYPE_CHECKING

from posthog.test.base import BaseTest, NonAtomicBaseTest

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Group, GroupTypeMapping, GroupUsageMetric, Organization, Tag, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.comment import Comment
from posthog.models.project import Project
from posthog.models.scoping import team_scope
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_group, insert_seed_group_type_mapping

from products.actions.backend.models.action import Action
from products.ai_observability.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.ai_observability.backend.models.score_definitions import ScoreDefinition
from products.ai_observability.backend.models.trace_reviews import TraceReview, TraceReviewScore
from products.alerts.backend.models.alert import AlertConfiguration
from products.annotations.backend.models.annotation import Annotation
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from products.business_knowledge.backend.models.constants import SourceStatus, SourceType
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import Cohort
from products.conversations.backend.models import Ticket
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.data_modeling.backend.facade.models import DataModelingJob, DataWarehouseSavedQuery
from products.early_access_features.backend.models import EarlyAccessFeature
from products.endpoints.backend.facade.models import Endpoint, EndpointVersion
from products.experiments.backend.models.experiment import Experiment
from products.exports.backend.models.exported_asset import ExportedAsset
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.logs.backend.models import LogsAlertConfiguration, LogsView
from products.notebooks.backend.models import Notebook, ResourceNotebook
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_variable import InsightVariable
from products.surveys.backend.models import Survey
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable as DataWarehouseTableModel,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

if TYPE_CHECKING:
    from products.customer_analytics.backend.models.account import Account
    from products.customer_analytics.backend.models.custom_property_definition import CustomPropertyDefinition
    from products.customer_analytics.backend.models.custom_property_value import CustomPropertyValue
    from products.customer_analytics.backend.models.relationship import (
        AccountRelationship,
        AccountRelationshipDefinition,
    )
    from products.error_tracking.backend.models import (
        ErrorTrackingAssignmentRule,
        ErrorTrackingBypassRule,
        ErrorTrackingIssue,
        ErrorTrackingIssueAssignment,
        ErrorTrackingIssueFingerprintV2,
        ErrorTrackingRelease,
        ErrorTrackingSuppressionRule,
        ErrorTrackingSymbolSet,
    )
else:
    Account = apps.get_model("customer_analytics", "Account")
    CustomPropertyDefinition = apps.get_model("customer_analytics", "CustomPropertyDefinition")
    CustomPropertyValue = apps.get_model("customer_analytics", "CustomPropertyValue")
    AccountRelationship = apps.get_model("customer_analytics", "AccountRelationship")
    AccountRelationshipDefinition = apps.get_model("customer_analytics", "AccountRelationshipDefinition")
    ErrorTrackingIssue = apps.get_model("error_tracking", "ErrorTrackingIssue")
    ErrorTrackingSymbolSet = apps.get_model("error_tracking", "ErrorTrackingSymbolSet")
    ErrorTrackingIssueAssignment = apps.get_model("error_tracking", "ErrorTrackingIssueAssignment")
    ErrorTrackingIssueFingerprintV2 = apps.get_model("error_tracking", "ErrorTrackingIssueFingerprintV2")
    ErrorTrackingAssignmentRule = apps.get_model("error_tracking", "ErrorTrackingAssignmentRule")
    ErrorTrackingBypassRule = apps.get_model("error_tracking", "ErrorTrackingBypassRule")
    ErrorTrackingSuppressionRule = apps.get_model("error_tracking", "ErrorTrackingSuppressionRule")
    ErrorTrackingRelease = apps.get_model("error_tracking", "ErrorTrackingRelease")

# Only directly-queryable tables are team-scoped via a WHERE clause. Namespace nodes such as
# `information_schema` carry no `table` of their own (just child catalog tables computed per-query),
# so they have no team_id filter and can't be `SELECT *`-ed directly — skip them here.
ALL_SYSTEM_TABLE_NAMES = sorted(name for name, node in SystemTables().children.items() if node.table is not None)

# {table_name: "sql_alias.column_name"} for team_id filter assertion
TEAM_ID_FILTER_PATTERNS = {
    "ingestion_warnings": "ingestion_warnings.team_id",  # ClickHouse-native table, no system__ prefix
    "teams": "system__teams.id",  # team_id is aliased to id column
    # Junction tables without team_id; isolation is enforced via an account_id IN system.accounts predicate
    "_account_resource_notebooks": "system__accounts.team_id",
    "_account_tagged_items": "system__accounts.team_id",
    "_account_custom_property_values": "system__accounts.team_id",
}


class TestSystemTablesTeamScoping(BaseTest):
    """Verify every system table's generated SQL includes a team_id WHERE clause."""

    @parameterized.expand(ALL_SYSTEM_TABLE_NAMES)
    def test_system_table_has_team_id_filter(self, table_name):
        db = Database.create_for(team=self.team, user=self.user)
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
            # Hidden junction tables that exist only to back the system.accounts lazy joins;
            # isolation is covered by TestSystemAccountsLazyJoins.
            "_account_resource_notebooks",
            "_account_tagged_items",
            "_account_custom_property_values",
            # information_schema is a namespace of virtual catalog tables (tables/columns/
            # relationships/data_types) computed per-query from the caller's own Database object,
            # so it has no team_id column to isolate; behaviour is covered by TestInformationSchema.
            "information_schema",
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
    from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination

    destination = BatchExportDestination.objects.create(type="S3", config={})
    return BatchExport.objects.create(team=team, name=f"export_{label}", destination=destination, interval="hour")


def _create_batch_export_backfill(team: Team, label: str):
    from products.batch_exports.backend.models.batch_export import (
        BatchExport,
        BatchExportBackfill,
        BatchExportDestination,
    )

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


def _create_account(team: Team, label: str) -> Account:
    return Account.objects.unscoped().create(team=team, name=f"account_{label}", external_id=f"ext_{label}")


def _create_custom_property_definition(team: Team, label: str) -> "CustomPropertyDefinition":
    return CustomPropertyDefinition.objects.unscoped().create(team=team, name=f"def_{label}", display_type="text")


def _create_account_relationship(team: Team, label: str) -> "AccountRelationship":
    account = Account.objects.unscoped().create(team=team, name=f"account_{label}")
    definition = AccountRelationshipDefinition.objects.unscoped().create(team=team, name=f"rel_{label}")
    return AccountRelationship.objects.unscoped().create(team=team, account=account, definition=definition)


def _create_account_relationship_definition(team: Team, label: str) -> "AccountRelationshipDefinition":
    return AccountRelationshipDefinition.objects.unscoped().create(team=team, name=f"rel_def_{label}")


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


def _create_dashboard_tile(team: Team, label: str) -> DashboardTile:
    dashboard = Dashboard.objects.create(team=team, name=f"dashboard_for_tile_{label}")
    insight = Insight.objects.create(team=team, short_id=f"tile_{label}"[:12], name=f"insight_{label}")
    return DashboardTile.objects.create(dashboard=dashboard, insight=insight)


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
    issue = ErrorTrackingIssue.objects.create(team=team, name=f"assigned_issue_{label}", status="active")
    return ErrorTrackingIssueAssignment.objects.create(team=team, issue=issue)


def _create_error_tracking_issue_fingerprint(team: Team, label: str):
    issue = ErrorTrackingIssue.objects.create(team=team, name=f"fp_issue_{label}", status="active")
    return ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=f"fp_{label}")


def _create_error_tracking_assignment_rule(team: Team, label: str):
    return ErrorTrackingAssignmentRule.objects.create(
        team=team, filters={"type": "AND", "values": []}, bytecode=[], order_key=0
    )


def _create_error_tracking_bypass_rule(team: Team, label: str):
    return ErrorTrackingBypassRule.objects.create(
        team=team, filters={"type": "AND", "values": []}, bytecode=[], order_key=0
    )


def _create_error_tracking_suppression_rule(team: Team, label: str):
    return ErrorTrackingSuppressionRule.objects.create(
        team=team, filters={"type": "AND", "values": []}, bytecode=[], order_key=0, sampling_rate=1.0
    )


def _create_error_tracking_release(team: Team, label: str):
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
    # Seed straight into the persons DB (off-Django psycopg) — the federated system table reads
    # it back from there. The personhog fake stays active for the HogQL Database build, so this
    # bypasses it deliberately via the low-level insert.
    with persons_db_connection(writer=True, autocommit=True) as conn:
        group_id = insert_seed_group(
            conn, team_id=team.id, group_key=f"group_{label}", group_type_index=0, group_properties={}, version=0
        )
    group = Group(team_id=team.id, group_key=f"group_{label}", group_type_index=0, group_properties={})
    group.id = group_id
    return group


def _create_group_type_mapping(team: Team, label: str) -> GroupTypeMapping:
    with persons_db_connection(writer=True, autocommit=True) as conn:
        mapping_id = insert_seed_group_type_mapping(
            conn, project_id=team.project_id, team_id=team.id, group_type=f"type_{label}", group_type_index=0
        )
    mapping = GroupTypeMapping(
        project_id=team.project_id, team_id=team.id, group_type=f"type_{label}", group_type_index=0
    )
    mapping.id = mapping_id
    return mapping


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


def _create_score_definition(team: Team, label: str) -> ScoreDefinition:
    user = _get_or_create_user_for_team(team, label)
    definition = ScoreDefinition.objects.create(
        team=team,
        name=f"score_definition_{label}",
        description="",
        kind=ScoreDefinition.Kind.BOOLEAN,
        created_by=user,
    )
    definition.create_new_version(
        config={"true_label": "Yes", "false_label": "No"},
        created_by=user,
    )
    return definition


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


def _create_support_ticket_message(team: Team, label: str) -> Comment:
    ticket = _create_support_ticket(team, label)
    return Comment.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=f"message_{label}",
        item_context={"author_type": "customer", "is_private": False},
    )


def _create_survey(team: Team, label: str) -> Survey:
    return Survey.objects.create(team=team, name=f"survey_{label}", type="popover")


def _create_task(team: Team, label: str):
    Task = apps.get_model("tasks", "Task")

    return Task.objects.create(
        team=team,
        title=f"task_{label}",
        description="x",
        origin_product=Task.OriginProduct.USER_CREATED,
    )


def _create_task_run(team: Team, label: str):
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")

    task = Task.objects.create(
        team=team,
        title=f"task_for_run_{label}",
        description="x",
        origin_product=Task.OriginProduct.USER_CREATED,
    )
    return TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.QUEUED)


def _create_file_system(team: Team, label: str):
    from posthog.models.file_system.file_system import FileSystem

    return FileSystem.objects.create(
        team=team,
        path=f"Channels/{label}",
        type="task",
        ref=label,
        surface="desktop",
    )


def _create_sandbox_environment(team: Team, label: str):
    SandboxEnvironment = apps.get_model("tasks", "SandboxEnvironment")

    # private=False so the row is queryable via HogQL — the privacy predicate
    # excludes private environments. Privacy filtering itself is covered by
    # TestSystemTablesSandboxEnvironmentPrivacy.
    return SandboxEnvironment.objects.create(team=team, name=f"env_{label}", private=False)


def _create_tag(team: Team, label: str) -> Tag:
    return Tag.objects.create(team=team, name=f"tag_{label}")


def _create_team(team: Team, label: str) -> Team:
    return team


def _create_usage_metric(team: Team, label: str) -> GroupUsageMetric:
    return GroupUsageMetric.objects.create(
        team=team,
        group_type_index=0,
        name=f"metric_{label}",
        filters={"events": []},
    )


def _create_business_knowledge_source(team: Team, label: str):
    with team_scope(team.pk):
        return KnowledgeSource.objects.create(
            team=team, name=f"bk_source_{label}", source_type=SourceType.TEXT, status=SourceStatus.READY
        )


def _create_business_knowledge_document(team: Team, label: str):
    with team_scope(team.pk):
        source = KnowledgeSource.objects.create(
            team=team, name=f"bk_source_for_doc_{label}", source_type=SourceType.TEXT, status=SourceStatus.READY
        )
        return KnowledgeDocument.objects.create(
            team=team, source=source, stable_id=f"stable_{label}", content=f"content_{label}"
        )


def _create_business_knowledge_chunk(team: Team, label: str):
    with team_scope(team.pk):
        source = KnowledgeSource.objects.create(
            team=team, name=f"bk_source_for_chunk_{label}", source_type=SourceType.TEXT, status=SourceStatus.READY
        )
        doc = KnowledgeDocument.objects.create(
            team=team, source=source, stable_id=f"stable_chunk_{label}", content=f"content_{label}"
        )
        return KnowledgeChunk.objects.create(
            id=uuid.uuid4(),
            team=team,
            source=source,
            document=doc,
            ordinal=0,
            content=f"chunk_content_{label}",
            char_count=len(f"chunk_content_{label}"),
        )


SYSTEM_TABLE_FACTORIES = [
    ("account_relationship_definitions", _create_account_relationship_definition),
    ("account_relationships", _create_account_relationship),
    ("accounts", _create_account),
    ("activity_logs", _create_activity_log),
    ("actions", _create_action),
    ("alerts", _create_alert),
    ("annotations", _create_annotation),
    ("batch_export_backfills", _create_batch_export_backfill),
    ("batch_exports", _create_batch_export),
    ("business_knowledge_chunks", _create_business_knowledge_chunk),
    ("business_knowledge_documents", _create_business_knowledge_document),
    ("business_knowledge_sources", _create_business_knowledge_source),
    ("cohorts", _create_cohort),
    ("cohort_calculation_history", _create_cohort_calculation_history),
    ("custom_property_definitions", _create_custom_property_definition),
    ("dashboards", _create_dashboard),
    ("dashboard_tiles", _create_dashboard_tile),
    ("data_modeling_jobs", _create_data_modeling_job),
    ("data_modeling_views", _create_data_warehouse_saved_query),
    ("data_warehouse_sources", _create_data_warehouse_source),
    ("data_warehouse_tables", _create_data_warehouse_table),
    ("early_access_features", _create_early_access_feature),
    ("data_modeling_endpoint_versions", _create_endpoint_version),
    ("data_modeling_endpoints", _create_endpoint),
    ("error_tracking_assignment_rules", _create_error_tracking_assignment_rule),
    ("error_tracking_bypass_rules", _create_error_tracking_bypass_rule),
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
    ("file_system", _create_file_system),
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
    ("score_definitions", _create_score_definition),
    ("session_recording_playlists", _create_session_recording_playlist),
    ("session_recordings", _create_session_recording),
    ("source_schemas", _create_source_schema),
    ("support_ticket_messages", _create_support_ticket_message),
    ("support_tickets", _create_support_ticket),
    ("surveys", _create_survey),
    ("tags", _create_tag),
    ("task_runs", _create_task_run),
    ("tasks", _create_task),
    ("teams", _create_team),
    ("trace_review_scores", _create_trace_review_score),
    ("trace_reviews", _create_trace_review),
    ("usage_metrics", _create_usage_metric),
]


class TestSystemTablesTeamIsolation(NonAtomicBaseTest):
    """Create entities in two teams and query via ClickHouse's postgresql() function
    to verify each team only sees its own data.

    Group/group_type_mapping rows are seeded straight into the persons DB via psycopg (what the
    federated system table reads), while the personhog fake stays active so the HogQL Database
    build's group-type lookup resolves. setUp truncates those persons tables because the psycopg
    writes commit outside Django's per-test transaction."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        # The group factories commit to the persons DB outside Django's transaction, so clear them
        # here for per-test isolation (this class isn't persons_db_direct, so the autouse truncate
        # fixture doesn't run).
        with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE posthog_group, posthog_grouptypemapping RESTART IDENTITY CASCADE")
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        self.other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

    @parameterized.expand(SYSTEM_TABLE_FACTORIES)
    def test_system_table_returns_only_own_team_data(self, table_name, factory):
        obj_team1 = factory(self.team, "team1")
        obj_team2 = factory(self.other_team, "team2")

        response = execute_hogql_query(f"SELECT id FROM system.{table_name}", team=self.team, user=self.user)
        ids = {str(row[0]) for row in response.results}

        assert str(obj_team1.pk) in ids
        assert str(obj_team2.pk) not in ids


class TestSystemTablesSandboxEnvironmentPrivacy(BaseTest):
    """Verify the sandbox_environments system table excludes private and internal environments,
    mirroring the REST API's per-creator visibility filter and internal-use exclusion."""

    def test_generated_sql_includes_private_predicate(self):
        db = Database.create_for(team=self.team, user=self.user)
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
        SandboxEnvironment = apps.get_model("tasks", "SandboxEnvironment")

        public_env = SandboxEnvironment.objects.create(team=self.team, name="public_env", private=False)
        private_env = SandboxEnvironment.objects.create(team=self.team, name="private_env", private=True)

        response = execute_hogql_query("SELECT id FROM system.sandbox_environments", team=self.team, user=self.user)
        ids = {str(row[0]) for row in response.results}

        assert str(public_env.pk) in ids
        assert str(private_env.pk) not in ids

    def test_internal_environments_excluded(self):
        SandboxEnvironment = apps.get_model("tasks", "SandboxEnvironment")

        regular_env = SandboxEnvironment.objects.create(
            team=self.team, name="regular_env", private=False, internal=False
        )
        internal_env = SandboxEnvironment.objects.create(
            team=self.team, name="internal_env", private=False, internal=True
        )

        response = execute_hogql_query("SELECT id FROM system.sandbox_environments", team=self.team, user=self.user)
        ids = {str(row[0]) for row in response.results}

        assert str(regular_env.pk) in ids
        assert str(internal_env.pk) not in ids


class TestSystemTablesTaskInternalExclusion(BaseTest):
    """Verify the tasks system table excludes internal tasks (signals pipeline, etc.)
    mirroring the REST API's default filter."""

    def test_generated_sql_includes_internal_predicate(self):
        db = Database.create_for(team=self.team, user=self.user)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        query, _ = prepare_and_print_ast(parse_select("SELECT id FROM system.tasks"), context, dialect="clickhouse")
        assert "system__tasks.internal" in query
        assert f"equals(system__tasks.team_id, {self.team.pk})" in query


class TestSystemTablesTaskInternalExclusionIsolation(NonAtomicBaseTest):
    """End-to-end check that internal tasks are never returned via HogQL."""

    CLASS_DATA_LEVEL_SETUP = False

    def test_internal_tasks_excluded(self):
        Task = apps.get_model("tasks", "Task")

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

        response = execute_hogql_query("SELECT id FROM system.tasks", team=self.team, user=self.user)
        ids = {str(row[0]) for row in response.results}

        assert str(regular_task.pk) in ids
        assert str(internal_task.pk) not in ids


class TestSystemTablesSupportTicketMessagesScope(NonAtomicBaseTest):
    """End-to-end check that support_ticket_messages only exposes ticket-scoped, non-deleted
    comments; other comment scopes (insight/dashboard discussions) must never leak through."""

    CLASS_DATA_LEVEL_SETUP = False

    def test_only_ticket_scoped_non_deleted_comments_returned(self):
        ticket = _create_support_ticket(self.team, "scope_test")
        message = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="visible message",
            item_context={"author_type": "support", "is_private": True},
        )
        other_scope = Comment.objects.create(
            team=self.team, scope="Insight", item_id="some-insight", content="insight discussion"
        )
        deleted = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="deleted message",
            deleted=True,
        )

        response = execute_hogql_query(
            "SELECT id, ticket_id, author_type, is_private FROM system.support_ticket_messages",
            team=self.team,
            user=self.user,
        )

        returned = [(str(row[0]), row[1], row[2], row[3]) for row in response.results]
        assert returned == [(str(message.pk), str(ticket.id), "support", 1)]
        assert str(other_scope.pk) not in {r[0] for r in returned}
        assert str(deleted.pk) not in {r[0] for r in returned}


class TestSystemTablesNotebookMarkdown(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_markdown_column_extracts_only_markdown_notebook_source(self):
        markdown_source = "# Title\n\nSome notebook markdown."
        Notebook.objects.create(
            team=self.team,
            short_id="mdnote",
            content={
                "type": "doc",
                "content": [
                    {
                        "type": "ph-markdown-notebook",
                        "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown_source},
                    }
                ],
            },
            text_content=markdown_source,
        )
        Notebook.objects.create(
            team=self.team,
            short_id="legacy",
            content={
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Legacy content"}]},
                ],
            },
            text_content="Legacy content",
        )
        Notebook.objects.create(team=self.team, short_id="empty", content=None, text_content=None)

        response = execute_hogql_query(
            "SELECT short_id, markdown FROM system.notebooks WHERE short_id IN ('mdnote', 'legacy', 'empty')",
            team=self.team,
            user=self.user,
        )
        rows = {row[0]: row[1] for row in response.results}

        assert rows == {"mdnote": markdown_source, "legacy": None, "empty": None}


class TestSystemAccountsLazyJoins(NonAtomicBaseTest):
    """Verify the `accounts.tags.names` and `accounts.notebooks.count` lazy joins."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        self.other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

    def test_tags_lazy_join_returns_tag_names_array(self):
        account = Account.objects.unscoped().create(team=self.team, name="A")
        billing = Tag.objects.create(name="billing", team=self.team)
        urgent = Tag.objects.create(name="urgent", team=self.team)
        account.tagged_items.create(tag=billing)
        account.tagged_items.create(tag=urgent)
        Account.objects.unscoped().create(team=self.team, name="B")  # untagged

        response = execute_hogql_query(
            "SELECT id, accounts.tags.names FROM system.accounts AS accounts ORDER BY name",
            team=self.team,
            user=self.user,
        )
        rows_by_id = {str(row[0]): row[1] for row in response.results}

        assert sorted(rows_by_id[str(account.id)]) == ["billing", "urgent"]

    def test_tags_lazy_join_isolated_per_team(self):
        other_account = Account.objects.unscoped().create(team=self.other_team, name="Theirs")
        other_tag = Tag.objects.create(name="billing", team=self.other_team)
        other_account.tagged_items.create(tag=other_tag)

        response = execute_hogql_query(
            "SELECT id, accounts.tags.names FROM system.accounts AS accounts",
            team=self.team,
            user=self.user,
        )
        assert response.results == []

    def test_notebooks_lazy_join_returns_count(self):
        account = Account.objects.unscoped().create(team=self.team, name="A")
        for label in ("n1", "n2", "n3"):
            notebook = Notebook.objects.create(team=self.team, title=label)
            ResourceNotebook.objects.create(notebook=notebook, account=account)
        Account.objects.unscoped().create(team=self.team, name="B")  # no notebooks

        response = execute_hogql_query(
            "SELECT id, accounts.notebooks.count FROM system.accounts AS accounts ORDER BY name",
            team=self.team,
            user=self.user,
        )
        rows_by_id = {str(row[0]): row[1] for row in response.results}

        assert rows_by_id[str(account.id)] == 3

    def _custom_property_value(self, account, definition, **value_kwargs):
        return CustomPropertyValue.objects.unscoped().create(
            team=self.team, account=account, definition=definition, **value_kwargs
        )

    def test_custom_properties_lazy_join_returns_value_by_definition_id(self):
        account = Account.objects.unscoped().create(team=self.team, name="A")
        definition = CustomPropertyDefinition.objects.unscoped().create(team=self.team, name="Plan")
        self._custom_property_value(account, definition, value_str="enterprise")

        response = execute_hogql_query(
            f"SELECT id, accounts.custom_properties.values.`{definition.id}` "
            "FROM system.accounts AS accounts ORDER BY name",
            team=self.team,
            user=self.user,
        )
        rows_by_id = {str(row[0]): row[1] for row in response.results}

        assert rows_by_id[str(account.id)] == "enterprise"

    def test_custom_properties_lazy_join_excludes_deleted_values(self):
        account = Account.objects.unscoped().create(team=self.team, name="A")
        definition = CustomPropertyDefinition.objects.unscoped().create(team=self.team, name="Plan")
        self._custom_property_value(account, definition, value_str="old", is_deleted=True)
        self._custom_property_value(account, definition, value_str="current")

        response = execute_hogql_query(
            f"SELECT accounts.custom_properties.values.`{definition.id}` FROM system.accounts AS accounts",
            team=self.team,
            user=self.user,
        )
        assert response.results[0][0] == "current"

    def test_custom_properties_lazy_join_isolated_per_team(self):
        # An account exists in self.team, so the query returns a row; the assertion only passes
        # if the other team's value is filtered out rather than leaking through the join.
        account = Account.objects.unscoped().create(team=self.team, name="Ours")
        other_account = Account.objects.unscoped().create(team=self.other_team, name="Theirs")
        other_definition = CustomPropertyDefinition.objects.unscoped().create(team=self.other_team, name="Plan")
        CustomPropertyValue.objects.unscoped().create(
            team=self.other_team, account=other_account, definition=other_definition, value_str="secret"
        )

        response = execute_hogql_query(
            f"SELECT id, accounts.custom_properties.values.`{other_definition.id}` FROM system.accounts AS accounts",
            team=self.team,
            user=self.user,
        )
        rows_by_id = {str(row[0]): row[1] for row in response.results}

        assert str(account.id) in rows_by_id
        assert rows_by_id[str(account.id)] != "secret"
        assert rows_by_id[str(account.id)] in (None, "")

    def _create_relationship_definition(self, name="CSM", **kwargs):
        return AccountRelationshipDefinition.objects.unscoped().create(team=self.team, name=name, **kwargs)

    def _create_relationship(self, account, definition, user, **kwargs):
        return AccountRelationship.objects.unscoped().create(
            team=self.team, account=account, definition=definition, user=user, **kwargs
        )

    def test_relationships_lazy_join_returns_active_user_ids_by_definition_id(self):
        account = Account.objects.unscoped().create(team=self.team, name="A")
        definition = self._create_relationship_definition()
        self._create_relationship(account, definition, self.user)
        Account.objects.unscoped().create(team=self.team, name="B")  # no relationships

        response = execute_hogql_query(
            f"SELECT id, accounts.relationships.values.`{definition.id}` "
            "FROM system.accounts AS accounts ORDER BY name",
            team=self.team,
            user=self.user,
        )
        rows_by_id = {str(row[0]): row[1] for row in response.results}

        assert rows_by_id[str(account.id)] == [self.user.id]

    def test_relationships_lazy_join_excludes_ended_rows(self):
        account = Account.objects.unscoped().create(team=self.team, name="A")
        definition = self._create_relationship_definition()
        self._create_relationship(account, definition, self.user, ended_at=timezone.now())

        response = execute_hogql_query(
            f"SELECT accounts.relationships.values.`{definition.id}` FROM system.accounts AS accounts",
            team=self.team,
            user=self.user,
        )
        assert response.results[0][0] in ([], None)

    def test_relationships_lazy_join_multi_holder_returns_all_active(self):
        account = Account.objects.unscoped().create(team=self.team, name="A")
        definition = self._create_relationship_definition(name="FDE", is_single_holder=False)
        other_user = self._create_user("fde2@posthog.com")
        self._create_relationship(account, definition, self.user)
        self._create_relationship(account, definition, other_user)

        response = execute_hogql_query(
            f"SELECT accounts.relationships.values.`{definition.id}` FROM system.accounts AS accounts",
            team=self.team,
            user=self.user,
        )
        assert sorted(response.results[0][0]) == sorted([self.user.id, other_user.id])

    def test_relationships_lazy_join_isolated_per_team(self):
        account = Account.objects.unscoped().create(team=self.team, name="Ours")
        other_account = Account.objects.unscoped().create(team=self.other_team, name="Theirs")
        other_definition = AccountRelationshipDefinition.objects.unscoped().create(team=self.other_team, name="CSM")
        AccountRelationship.objects.unscoped().create(
            team=self.other_team, account=other_account, definition=other_definition, user=self.user
        )

        response = execute_hogql_query(
            f"SELECT id, accounts.relationships.values.`{other_definition.id}` FROM system.accounts AS accounts",
            team=self.team,
            user=self.user,
        )
        rows_by_id = {str(row[0]): row[1] for row in response.results}

        assert str(account.id) in rows_by_id
        assert rows_by_id[str(account.id)] in ([], None)
