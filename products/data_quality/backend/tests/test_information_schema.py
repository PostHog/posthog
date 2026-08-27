from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun


def _fail_queries_for_table(table_name: str):
    def wrapper(execute, sql, params, many, context):
        if table_name in sql:
            raise DatabaseError(f"Failed to load {table_name}")
        return execute(sql, params, many, context)

    return wrapper


class TestInformationSchemaDataQuality(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patch = patch(
            "products.data_quality.backend.facade.flags.is_data_quality_checks_enabled", return_value=True
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)
        self.subject_uuid = uuid4()

    def _context(self, denied_tables: set[str] | None = None) -> HogQLContext:
        database = Database.create_for(team=self.team, user=self.user)
        if denied_tables:
            database._denied_tables |= denied_tables
        return HogQLContext(team=self.team, team_id=self.team.pk, database=database)

    def _check(self, team: Team | None = None, **kwargs) -> DataQualityCheck:
        team = team or self.team
        defaults = {
            "team": team,
            "subject_type": SubjectType.VIEW,
            "saved_query_id": self.subject_uuid,
            "subject_name": "orders",
            "check_type": CheckType.NOT_NULL,
            "column_name": "customer_id",
            "fingerprint": uuid4().hex,
        }
        return DataQualityCheck.objects.for_team(team.id).create(**{**defaults, **kwargs})

    def _run_for(self, check: DataQualityCheck, **kwargs) -> DataQualityCheckRun:
        suite_run = DataQualitySuiteRun.objects.for_team(check.team_id).create(team=check.team, trigger="manual")
        defaults = {
            "team": check.team,
            "quality_check": check,
            "suite_run": suite_run,
            "subject_type": check.subject_type,
            "subject_uuid": check.subject_uuid,
            "subject_name": check.subject_name,
            "check_type": check.check_type,
            "check_fingerprint": check.fingerprint,
            "status": CheckRunStatus.FAILED,
            "failed_row_count": 4,
        }
        return DataQualityCheckRun.objects.for_team(check.team_id).create(**{**defaults, **kwargs})

    def _query(self, sql: str, context: HogQLContext | None = None) -> list:
        return execute_hogql_query(sql, team=self.team, context=context or self._context()).results

    def test_checks_are_discoverable_with_their_config(self) -> None:
        self._check(
            name="orders_status_accepted",
            check_type=CheckType.ACCEPTED_VALUES,
            column_name="status",
            config={"values": ["paid"]},
        )

        rows = self._query(
            "SELECT name, subject_name, check_type, config, severity FROM system.information_schema.data_quality_checks"
        )

        assert rows == [("orders_status_accepted", "orders", "accepted_values", '{"values": ["paid"]}', "error")]

    def test_deleted_checks_disappear_but_their_runs_stay_queryable(self) -> None:
        check = self._check()
        self._run_for(check)
        DataQualityCheck.objects.for_team(self.team.id).filter(pk=check.pk).update(deleted=True)

        assert self._query("SELECT id FROM system.information_schema.data_quality_checks") == []
        assert len(self._query("SELECT id FROM system.information_schema.data_quality_check_runs")) == 1

    def test_rows_are_scoped_to_the_querying_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        self._check(team=other_team, subject_name="their_orders")
        self._check(subject_name="our_orders")

        rows = self._query("SELECT subject_name FROM system.information_schema.data_quality_checks")

        assert rows == [("our_orders",)]

    @parameterized.expand(
        [
            ("no_checks", [], "unknown", 0),
            ("passing", [(CheckSeverity.ERROR, CheckRunStatus.PASSED)], "healthy", 0),
            (
                "error_severity_failure",
                [(CheckSeverity.ERROR, CheckRunStatus.FAILED), (CheckSeverity.WARN, CheckRunStatus.PASSED)],
                "failing",
                1,
            ),
            ("warn_only", [(CheckSeverity.WARN, CheckRunStatus.FAILED)], "warn", 1),
            ("execution_error", [(CheckSeverity.ERROR, CheckRunStatus.ERRORED)], "erroring", 0),
        ]
    )
    def test_health_matches_the_rest_endpoints_rollup(
        self, _name, states: list[tuple], expected_health: str, expected_failing: int
    ) -> None:
        for index, (severity, last_status) in enumerate(states):
            self._check(column_name=f"col_{index}", severity=severity, last_status=last_status)

        rows = self._query(
            "SELECT health, checks_total, checks_failing FROM system.information_schema.data_quality_health"
        )

        if not states:
            assert rows == []
            return
        assert rows == [(expected_health, len(states), expected_failing)]

    @parameterized.expand(
        [
            ("data_quality_checks", "data_quality_dataqualitycheck"),
            ("data_quality_check_runs", "data_quality_dataqualitycheckrun"),
            ("data_quality_health", "data_quality_dataqualitycheck"),
        ]
    )
    def test_a_broken_loader_degrades_to_no_rows(self, table: str, db_table: str) -> None:
        check = self._check()
        self._run_for(check)

        with CaptureQueriesContext(connection):
            with connection.execute_wrapper(_fail_queries_for_table(db_table)):
                results = self._query(f"SELECT * FROM system.information_schema.{table}")

        assert results == []

    @parameterized.expand(
        [
            ("checks", "SELECT subject_name FROM system.information_schema.data_quality_checks"),
            ("check_runs", "SELECT subject_name FROM system.information_schema.data_quality_check_runs"),
            ("health", "SELECT subject_name FROM system.information_schema.data_quality_health"),
        ]
    )
    def test_a_denied_subject_is_hidden_from_every_data_quality_table(self, _name: str, sql: str) -> None:
        denied = self._check(subject_name="orders", saved_query_id=uuid4())
        self._run_for(denied)
        allowed = self._check(subject_name="customers", saved_query_id=uuid4(), column_name="id")
        self._run_for(allowed)

        rows = self._query(sql, context=self._context(denied_tables={"orders"}))

        assert ("orders",) not in rows
        assert ("customers",) in rows

    @parameterized.expand(
        [
            ("checks", "SELECT subject_name FROM system.information_schema.data_quality_checks"),
            ("check_runs", "SELECT subject_name FROM system.information_schema.data_quality_check_runs"),
            ("health", "SELECT subject_name FROM system.information_schema.data_quality_health"),
        ]
    )
    def test_a_denied_subject_renamed_since_its_last_run_stays_hidden(self, _name: str, sql: str) -> None:
        # The name on the check is only rewritten when the check runs, so matching denial against it
        # serves the subject's rows for the whole window between a rename and the next run.
        renamed = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        stale = self._check(subject_name="orders_legacy", saved_query_id=renamed.id)
        self._run_for(stale)

        rows = self._query(sql, context=self._context(denied_tables={"orders"}))

        assert rows == []

    @parameterized.expand(
        [
            ("checks", "SELECT subject_name FROM system.information_schema.data_quality_checks"),
            ("check_runs", "SELECT subject_name FROM system.information_schema.data_quality_check_runs"),
            ("health", "SELECT subject_name FROM system.information_schema.data_quality_health"),
        ]
    )
    def test_a_check_reading_a_denied_subject_is_hidden_from_every_table(self, _name: str, sql: str) -> None:
        # A check on an allowed parent still names the denied subject in its config, and its status
        # answers questions about the rows behind it.
        reader = self._check(
            subject_name="customers",
            saved_query_id=uuid4(),
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT 1 FROM orders"},
        )
        self._run_for(reader, check_config=reader.config)

        rows = self._query(sql, context=self._context(denied_tables={"orders"}))

        assert rows == []

    @parameterized.expand(
        [
            ("checks", "SELECT subject_name FROM system.information_schema.data_quality_checks"),
            ("health", "SELECT subject_name FROM system.information_schema.data_quality_health"),
        ]
    )
    def test_a_check_whose_last_run_read_a_recreated_subject_stays_hidden(self, _name: str, sql: str) -> None:
        # A check row is not only a definition: last_status is the verdict of its last run, over
        # whatever that run read. Once the subject it read is deleted and its name taken by something
        # the caller may read, the definition stops naming anything denied while the verdict remains.
        original = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders_original", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        original_id = original.id
        original.delete()
        reader = self._check(
            subject_name="customers",
            saved_query_id=self.subject_uuid,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT 1 FROM orders"},
            last_status=CheckRunStatus.FAILED,
        )
        self._run_for(
            reader,
            check_config=reader.config,
            referenced_subjects=[{"subject_type": str(SubjectType.VIEW), "subject_uuid": str(original_id)}],
        )

        rows = self._query(sql, context=self._context(denied_tables={"secrets"}))

        assert rows == []

    def test_a_run_whose_subject_was_recreated_under_the_same_name_stays_hidden(self) -> None:
        # Deleting a warehouse object frees its name for anyone to take. Matched by the names in its
        # definition, the run that read the original would be served here the moment something the
        # caller can read answers to that name -- with its failed-row count over the original's rows.
        original = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders_original", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        original_id = original.id
        original.delete()
        reader = self._check(
            subject_name="customers",
            saved_query_id=uuid4(),
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT 1 FROM orders"},
        )
        self._run_for(
            reader,
            check_config=reader.config,
            referenced_subjects=[{"subject_type": str(SubjectType.VIEW), "subject_uuid": str(original_id)}],
        )

        # A denial the caller still has, so the gate engages: an empty denied set skips it entirely.
        rows = self._query(
            "SELECT subject_name FROM system.information_schema.data_quality_check_runs",
            context=self._context(denied_tables={"secrets"}),
        )

        assert rows == []

    def test_the_tables_are_absent_when_the_catalog_flag_is_off(self) -> None:
        with patch("products.data_quality.backend.facade.flags.is_data_quality_checks_enabled", return_value=False):
            listing = self._query(
                "SELECT table_name FROM system.information_schema.tables WHERE table_name ILIKE '%data_quality%'",
                context=HogQLContext(
                    team=self.team,
                    team_id=self.team.pk,
                    database=Database.create_for(team=self.team, user=self.user),
                ),
            )

        assert listing == []
