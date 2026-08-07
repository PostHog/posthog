from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import CheckType, SubjectType
from products.data_quality.backend.logic.compiler import compile_check
from products.data_quality.backend.logic.contracts import SubjectRef

_STRING = {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}
_INT = {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}
_DATETIME = {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "valid": True}

# A UUID the relationships config needs but that never reaches the SQL -- build() reads the related
# SubjectRef, not this id.
_UNUSED_UUID = "1cd4a1ef-0000-0000-0000-0000000000ff"


class TestCheckExecutionAgainstClickHouse(ClickhouseTestMixin, APIBaseTest):
    """Compiled checks must run in ClickHouse and count failures correctly, not just print.

    Each case builds a view of constant rows -- so passing and failing data is exact and needs no
    ingestion -- compiles the check against it, then runs the aggregate the runner would run. This
    catches a query that prints but errors in ClickHouse, or returns the wrong count, which the
    printed-shape assertions in test_compiler cannot.
    """

    def _view(self, name: str, body: str, columns: dict[str, Any]) -> SubjectRef:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": body},
            columns=columns,
        )
        return SubjectRef(
            subject_type=SubjectType.VIEW,
            subject_uuid=str(saved_query.id),
            name=name,
            queryable_name=name,
            exists=True,
        )

    def _execute(self, subject, check_type, column_name, config, related=None) -> list:
        compiled = compile_check(
            check_type=check_type,
            subject=subject,
            column_name=column_name,
            config=config,
            related_subject=related,
        )
        results = execute_hogql_query(compiled.query, team=self.team).results
        assert results is not None
        return results[0]

    def _failure_count(self, subject, check_type, column_name, config, related=None) -> int:
        # A ZERO_ROWS_PASS check selects (failure_count, observed_value); the runner reads column 0.
        return self._execute(subject, check_type, column_name, config, related)[0]

    @parameterized.expand(
        [
            (
                "not_null",
                "SELECT 1 AS customer_id UNION ALL SELECT NULL UNION ALL SELECT 2 UNION ALL SELECT NULL",
                "SELECT 1 AS customer_id UNION ALL SELECT 2",
                {"customer_id": _INT},
                CheckType.NOT_NULL,
                "customer_id",
                {},
                2,
            ),
            (
                "unique",
                "SELECT 1 AS id UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 3",
                "SELECT 1 AS id UNION ALL SELECT 2 UNION ALL SELECT 3",
                {"id": _INT},
                CheckType.UNIQUE,
                "id",
                {},
                2,
            ),
            (
                "accepted_values",
                "SELECT 'paid' AS status UNION ALL SELECT 'refunded' UNION ALL SELECT 'unknown' UNION ALL SELECT NULL",
                "SELECT 'paid' AS status UNION ALL SELECT 'refunded' UNION ALL SELECT NULL",
                {"status": _STRING},
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid", "refunded"]},
                1,
            ),
        ]
    )
    def test_zero_rows_pass_types_count_failures(
        self, name, failing_body, passing_body, columns, check_type, column_name, config, expected_failures
    ) -> None:
        failing = self._view(f"{name}_fail", failing_body, columns)
        assert self._failure_count(failing, check_type, column_name, config) == expected_failures

        passing = self._view(f"{name}_pass", passing_body, columns)
        assert self._failure_count(passing, check_type, column_name, config) == 0

    def test_custom_sql_counts_returned_rows(self) -> None:
        columns = {"total": _INT}
        failing = self._view("cs_fail", "SELECT 5 AS total UNION ALL SELECT -1 UNION ALL SELECT -2", columns)
        assert (
            self._failure_count(failing, CheckType.CUSTOM_SQL, "", {"query": "SELECT 1 FROM cs_fail WHERE total < 0"})
            == 2
        )

        passing = self._view("cs_pass", "SELECT 5 AS total UNION ALL SELECT 1", columns)
        assert (
            self._failure_count(passing, CheckType.CUSTOM_SQL, "", {"query": "SELECT 1 FROM cs_pass WHERE total < 0"})
            == 0
        )

    def test_relationships_counts_rows_with_no_match(self) -> None:
        customers = self._view("rel_customers", "SELECT 1 AS id UNION ALL SELECT 2", {"id": _INT})
        config = {"to_subject_type": "view", "to_subject_uuid": _UNUSED_UUID, "to_column": "id"}

        orders = self._view(
            "rel_orders_fail",
            "SELECT 1 AS customer_id UNION ALL SELECT 2 UNION ALL SELECT 99 UNION ALL SELECT NULL",
            {"customer_id": _INT},
        )
        assert self._failure_count(orders, CheckType.RELATIONSHIPS, "customer_id", config, related=customers) == 1

        matched = self._view("rel_orders_pass", "SELECT 1 AS customer_id UNION ALL SELECT 2", {"customer_id": _INT})
        assert self._failure_count(matched, CheckType.RELATIONSHIPS, "customer_id", config, related=customers) == 0

    def test_row_count_observes_the_table_count(self) -> None:
        # BOUNDS selects only observed_value; the runner compares it to min/max itself.
        view = self._view("rc_view", "SELECT 1 AS x UNION ALL SELECT 2 UNION ALL SELECT 3", {"x": _INT})
        observed = self._execute(view, CheckType.ROW_COUNT, "", {"min": 1})[0]
        assert observed == 3

    def test_freshness_passes_for_a_recent_value(self) -> None:
        view = self._view("fresh_recent", "SELECT now() AS created_at", {"created_at": _DATETIME})
        assert self._failure_count(view, CheckType.FRESHNESS, "created_at", {"max_age_minutes": 60}) == 0

    def test_freshness_fails_for_a_stale_value(self) -> None:
        view = self._view(
            "fresh_stale", "SELECT toDateTime('2020-01-01 00:00:00') AS created_at", {"created_at": _DATETIME}
        )
        assert self._failure_count(view, CheckType.FRESHNESS, "created_at", {"max_age_minutes": 60}) == 1

    @parameterized.expand(
        [
            # An empty table and an all-null column both leave the newest timestamp undefined; freshness
            # must treat that as a failure, not silently pass by comparing null to the threshold.
            ("empty_table", "SELECT toDateTime('2020-01-01 00:00:00') AS created_at LIMIT 0"),
            ("all_null_column", "SELECT nullIf(now(), now()) AS created_at"),
        ]
    )
    def test_freshness_fails_when_there_is_no_value(self, _name, body) -> None:
        view = self._view(f"fresh_{_name}", body, {"created_at": _DATETIME})
        assert self._failure_count(view, CheckType.FRESHNESS, "created_at", {"max_age_minutes": 60}) == 1
