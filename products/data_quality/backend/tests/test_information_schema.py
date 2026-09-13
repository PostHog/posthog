from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.schema import CachedHogQLQueryResponse, CacheMissResponse, HogQLQuery

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.facade.models import Metric
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.api import record_check_run
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


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
        self.subject = self._view("orders")
        self.subject_uuid = self.subject.id

    def _view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

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
        return record_check_run(check.team_id, **{**defaults, **kwargs})

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

    @parameterized.expand([("data_quality_checks",), ("data_quality_check_runs",), ("data_quality_health",)])
    def test_catalog_denial_hides_metric_definitions_history_and_health(self, table: str) -> None:
        metric = Metric.objects.for_team(self.team.id).create(
            team=self.team,
            name="signups",
            definition={"kind": "HogQLQuery", "query": "SELECT 1 AS signups"},
            referenced_table_names=[],
        )
        check = self._check(
            subject_type=SubjectType.METRIC,
            saved_query_id=None,
            metric_id=metric.id,
            subject_name="signups",
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT * FROM {metric}"},
        )
        self._run_for(check, referenced_subjects=[])
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save(update_fields=["available_product_features"])
        denied_user = self._create_user("catalog-denied@example.com")
        AccessControl.objects.create(
            team=self.team,
            resource="data_catalog",
            organization_member=denied_user.organization_memberships.get(organization=self.organization),
            access_level="none",
        )
        query = HogQLQuery(query=f"SELECT subject_name FROM system.information_schema.{table}")
        allowed_runner = HogQLQueryRunner(query=query, team=self.team, user=self.user)
        denied_runner = HogQLQueryRunner(query=query, team=self.team, user=denied_user)
        allowed_response = allowed_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(allowed_response, CachedHogQLQueryResponse)
        assert allowed_response.is_cached is False
        assert allowed_response.results == [("signups",)]
        allowed_cached_response = allowed_runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
        assert isinstance(allowed_cached_response, CachedHogQLQueryResponse)
        assert allowed_cached_response.is_cached is True
        assert allowed_cached_response.results == [["signups"]]

        denied_cache_miss = denied_runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
        assert isinstance(denied_cache_miss, CacheMissResponse)
        denied_response = denied_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(denied_response, CachedHogQLQueryResponse)
        assert denied_response.results == []
        assert denied_response.is_cached is False
        denied_cached_response = denied_runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
        assert isinstance(denied_cached_response, CachedHogQLQueryResponse)
        assert denied_cached_response.is_cached is True
        assert denied_cached_response.results == []

    def test_catalog_only_member_can_discover_only_metric_checks(self) -> None:
        self._check()
        metric = Metric.objects.for_team(self.team.id).create(
            team=self.team,
            name="signups",
            definition={"kind": "HogQLQuery", "query": "SELECT 1 AS value"},
            referenced_table_names=[],
        )
        metric_check = self._check(
            subject_type=SubjectType.METRIC,
            saved_query_id=None,
            metric_id=metric.id,
            subject_name=metric.name,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT * FROM {metric}"},
        )
        self._run_for(metric_check, referenced_subjects=[])
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_objects",
            organization_member=self.organization_membership,
            access_level="none",
        )
        cache.clear()
        for table in ("data_quality_checks", "data_quality_check_runs", "data_quality_health"):
            assert self._query(f"SELECT subject_name FROM system.information_schema.{table}") == [("signups",)]

    @parameterized.expand([("catalog_member", True), ("catalog_denied", False)])
    def test_a_query_scoped_token_reads_metric_checks_on_the_users_own_catalog_access(
        self, _name: str, allowed: bool
    ) -> None:
        metric = Metric.objects.for_team(self.team.id).create(
            team=self.team,
            name="signups",
            definition={"kind": "HogQLQuery", "query": "SELECT 1 AS value"},
            referenced_table_names=[],
        )
        self._check(
            subject_type=SubjectType.METRIC,
            saved_query_id=None,
            metric_id=metric.id,
            subject_name=metric.name,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT * FROM {metric}"},
        )
        if not allowed:
            self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
            self.organization.save(update_fields=["available_product_features"])
            AccessControl.objects.create(
                team=self.team,
                resource="data_catalog",
                organization_member=self.organization_membership,
                access_level="none",
            )
            cache.clear()
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="raw hogql", secure_value=hash_key_value(token), scopes=["query:read"]
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/query/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT subject_name FROM system.information_schema.data_quality_checks "
                    "WHERE subject_type = 'metric'",
                }
            },
            format="json",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200, response.content
        assert response.json()["results"] == ([["signups"]] if allowed else [])

    def test_soft_deleted_subject_hides_active_checks_but_preserves_admin_history(self) -> None:
        check = self._check()
        self._run_for(check)
        self.subject.deleted = True
        self.subject.save(update_fields=["deleted"])
        assert self._query("SELECT id FROM system.information_schema.data_quality_checks") == []
        assert self._query("SELECT subject_uuid FROM system.information_schema.data_quality_health") == []
        assert len(self._query("SELECT id FROM system.information_schema.data_quality_check_runs")) == 1

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
        denied = self._check(subject_name="orders")
        self._run_for(denied)
        allowed = self._check(subject_name="customers", saved_query_id=self._view("customers").id, column_name="id")
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
        stale = self._check(subject_name="orders_legacy")
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
            saved_query_id=self._view("customers").id,
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
        original = self._view("orders_original")
        original_id = original.id
        original.delete()
        reader = self._check(
            subject_name="customers",
            saved_query_id=self._view("customers").id,
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
        original = self._view("orders_original")
        original_id = original.id
        original.delete()
        reader = self._check(
            subject_name="customers",
            saved_query_id=self._view("customers").id,
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

    def test_a_backing_table_reference_stays_hidden_after_its_view_is_renamed(self) -> None:
        referenced_view = self._view("customers")
        backing_table = DataWarehouseTable.objects.create(
            team=self.team,
            name=referenced_view.name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=f"s3://bucket/{referenced_view.folder_path}/{referenced_view.normalized_name}",
        )
        referenced_view.table = backing_table
        referenced_view.is_materialized = True
        referenced_view.save(update_fields=["table", "is_materialized"])
        check = self._check(
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT 1 FROM customers"},
        )
        self._run_for(
            check,
            check_config=check.config,
            referenced_subjects=[{"subject_type": str(SubjectType.TABLE), "subject_uuid": str(backing_table.id)}],
        )
        referenced_view.name = "customers_v2"
        referenced_view.save(update_fields=["name"])

        rows = self._query(
            "SELECT subject_name FROM system.information_schema.data_quality_check_runs",
            context=self._context(denied_tables={"customers_v2"}),
        )

        assert rows == []

    @parameterized.expand(
        [
            ("non_referencing", CheckType.NOT_NULL, {}, ["orders"]),
            ("referencing", CheckType.CUSTOM_SQL, {"query": "SELECT 1 FROM customers"}, []),
        ]
    )
    def test_a_run_predating_pinned_references_is_judged_by_its_type(
        self, _name: str, check_type: str, config: dict, expected: list[str]
    ) -> None:
        # Nothing backfills the references of a run recorded before they were pinned, so a null column
        # cannot be read as "touched nothing". A type that cannot reach past its own subject read only
        # the subject already authorized here; one that can is withheld.
        check = self._check(check_type=check_type, column_name="", config=config)
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            quality_check=check,
            suite_run=suite_run,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.subject_uuid,
            subject_name="orders",
            check_type=check_type,
            check_fingerprint=check.fingerprint,
            status=CheckRunStatus.FAILED,
            referenced_subjects=None,
        )

        rows = self._query(
            "SELECT subject_name FROM system.information_schema.data_quality_check_runs",
            context=self._context(denied_tables={"secrets"}),
        )

        assert [name for (name,) in rows] == expected

    def test_a_run_whose_declared_subject_was_deleted_is_withheld_from_a_restricted_member(self) -> None:
        # Deleting a subject takes its denial with it, so nothing left can show the caller was allowed
        # it. Hidden until retention deletes the history, rather than served on the strength of a name
        # anyone can now claim.
        temp = self._view("temp_orders")
        check = self._check(subject_name="temp_orders", saved_query_id=temp.id)
        self._run_for(check)
        temp.delete()

        rows = self._query(
            "SELECT subject_name FROM system.information_schema.data_quality_check_runs",
            context=self._context(denied_tables={"secrets"}),
        )

        assert rows == []

    def test_a_run_referencing_an_unknown_subject_type_is_withheld(self) -> None:
        # A future subject kind recorded before this gate learns it matches no readable branch, so it
        # is contained in nothing and the run falls out -- the fail-closed answer, not the reverse.
        check = self._check(check_type=CheckType.CUSTOM_SQL, column_name="", config={"query": "SELECT 1"})
        self._run_for(
            check,
            check_type=CheckType.CUSTOM_SQL,
            referenced_subjects=[{"subject_type": "dashboard", "subject_uuid": str(self.subject_uuid)}],
        )

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
