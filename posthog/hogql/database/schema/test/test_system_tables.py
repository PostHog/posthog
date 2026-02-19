from posthog.test.base import BaseTest, NonAtomicBaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import (
    Action,
    Cohort,
    Dashboard,
    Experiment,
    ExportedAsset,
    FeatureFlag,
    Group,
    GroupTypeMapping,
    Insight,
    InsightVariable,
    Organization,
    Survey,
    Team,
)
from posthog.models.cohort.calculation_history import CohortCalculationHistory
from posthog.models.project import Project

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable as DataWarehouseTableModel
from products.error_tracking.backend.models import ErrorTrackingIssue
from products.notebooks.backend.models import Notebook

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


def _create_action(team: Team, label: str) -> Action:
    return Action.objects.create(team=team, name=f"action_{label}")


def _create_cohort(team: Team, label: str) -> Cohort:
    return Cohort.objects.create(team=team, name=f"cohort_{label}")


def _create_cohort_calculation_history(team: Team, label: str) -> CohortCalculationHistory:
    cohort = Cohort.objects.create(team=team, name=f"cohort_for_calc_{label}")
    return CohortCalculationHistory.objects.create(team=team, cohort=cohort, filters={})


def _create_dashboard(team: Team, label: str) -> Dashboard:
    return Dashboard.objects.create(team=team, name=f"dashboard_{label}")


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


def _create_error_tracking_issue(team: Team, label: str) -> ErrorTrackingIssue:
    return ErrorTrackingIssue.objects.create(team=team, name=f"issue_{label}", status="active")


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


def _create_insight(team: Team, label: str) -> Insight:
    return Insight.objects.create(team=team, name=f"insight_{label}")


def _create_insight_variable(team: Team, label: str) -> InsightVariable:
    return InsightVariable.objects.create(team=team, name=f"var_{label}", type="String")


def _create_notebook(team: Team, label: str) -> Notebook:
    return Notebook.objects.create(team=team, title=f"notebook_{label}")


def _create_survey(team: Team, label: str) -> Survey:
    return Survey.objects.create(team=team, name=f"survey_{label}", type="popover")


def _create_team(team: Team, label: str) -> Team:
    return team


SYSTEM_TABLE_FACTORIES = [
    ("actions", _create_action),
    ("cohorts", _create_cohort),
    ("cohort_calculation_history", _create_cohort_calculation_history),
    ("dashboards", _create_dashboard),
    ("data_warehouse_sources", _create_data_warehouse_source),
    ("data_warehouse_tables", _create_data_warehouse_table),
    ("error_tracking_issues", _create_error_tracking_issue),
    ("experiments", _create_experiment),
    ("exports", _create_export),
    ("feature_flags", _create_feature_flag),
    ("groups", _create_group),
    ("group_type_mappings", _create_group_type_mapping),
    ("insights", _create_insight),
    ("insight_variables", _create_insight_variable),
    ("notebooks", _create_notebook),
    ("surveys", _create_survey),
    ("teams", _create_team),
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
