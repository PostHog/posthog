from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import CheckType, SubjectType
from products.data_quality.backend.logic.compiler import compile_check
from products.data_quality.backend.logic.contracts import CompiledCheck, SubjectRef

_STRING = {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"}
_INT = {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}
_DATETIME = {"hogql": "DateTimeDatabaseField", "clickhouse": "Nullable(DateTime)"}

# id | customer_id | status: one null customer_id, a duplicate id, a status outside the allowed set,
# and a customer_id (c9) with no matching customer -- so every assertion below has a known count.
_ORDERS_QUERY = (
    "SELECT 1 AS id, 'c1' AS customer_id, 'paid' AS status "
    "UNION ALL SELECT 2, 'c2', 'refunded' "
    "UNION ALL SELECT 3, nullIf('', ''), 'paid' "
    "UNION ALL SELECT 3, 'c9', 'shipped'"
)

_NULL_CUSTOMER_ROW = {"id": 3, "customer_id": None, "status": "paid"}
_UNMATCHED_CUSTOMER_ROW = {"id": 3, "customer_id": "c9", "status": "shipped"}


class TestCompiledCheckExecution(ClickhouseTestMixin, APIBaseTest):
    """Compiled checks must run in ClickHouse and count what the data actually contains.

    Views of constant rows, so the expected counts are exact and nothing has to be ingested. This
    catches a query that prints but errors in ClickHouse, or returns the wrong number, neither of
    which the printed-shape assertions in test_compiler can see.
    """

    def setUp(self) -> None:
        super().setUp()
        self._subjects: dict[str, SubjectRef] = {}
        self._view("orders", _ORDERS_QUERY, {"id": _INT, "customer_id": _STRING, "status": _STRING})
        self._view("customers", "SELECT 'c1' AS id UNION ALL SELECT 'c2'", {"id": _STRING})
        self._view("all_customers", "SELECT 'c1' AS id UNION ALL SELECT 'c2' UNION ALL SELECT 'c9'", {"id": _STRING})
        self._view("fresh_orders", "SELECT now() AS created_at", {"created_at": _DATETIME})
        self._view("stale_orders", "SELECT toDateTime('2000-01-01 00:00:00') AS created_at", {"created_at": _DATETIME})
        self._view("empty_orders", "SELECT now() AS created_at LIMIT 0", {"created_at": _DATETIME})
        self._view(
            "null_ts_orders",
            "SELECT nullIf(now(), now()) AS created_at UNION ALL SELECT nullIf(now(), now())",
            {"created_at": _DATETIME},
        )

    def _view(self, name: str, query: str, columns: dict[str, Any]) -> None:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": query}, columns=columns
        )
        self._subjects[name] = SubjectRef(SubjectType.VIEW, str(saved_query.id), name, name, exists=True)

    def _compile(self, view_name, check_type, column_name, config, related_view=None) -> CompiledCheck:
        return compile_check(
            check_type=check_type,
            subject=self._subjects[view_name],
            column_name=column_name,
            config=config,
            related_subject=self._subjects[related_view] if related_view else None,
        )

    def _execute(self, query) -> Any:
        return execute_hogql_query(
            query=query,
            team=self.team,
            query_type="data_quality_check",
            bypass_warehouse_access_control=True,
        )

    def _relationships_config(self) -> dict:
        return {
            "to_subject_type": "view",
            "to_subject_uuid": self._subjects["customers"].subject_uuid,
            "to_column": "id",
        }

    @parameterized.expand(
        [
            ("not_null_pass", "orders", CheckType.NOT_NULL, "status", {}, None, 0),
            ("not_null_fail", "orders", CheckType.NOT_NULL, "customer_id", {}, None, 1),
            ("unique_pass", "orders", CheckType.UNIQUE, "customer_id", {}, None, 0),
            ("unique_fail", "orders", CheckType.UNIQUE, "id", {}, None, 1),
            (
                "accepted_values_pass",
                "orders",
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid", "refunded", "shipped"]},
                None,
                0,
            ),
            (
                "accepted_values_fail",
                "orders",
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid", "refunded"]},
                None,
                1,
            ),
            ("relationships_pass", "orders", CheckType.RELATIONSHIPS, "customer_id", None, "all_customers", 0),
            ("relationships_fail", "orders", CheckType.RELATIONSHIPS, "customer_id", None, "customers", 1),
            (
                "custom_sql_pass",
                "orders",
                CheckType.CUSTOM_SQL,
                "",
                {"query": "SELECT id FROM orders WHERE id < 0"},
                None,
                0,
            ),
            (
                "custom_sql_fail",
                "orders",
                CheckType.CUSTOM_SQL,
                "",
                {"query": "SELECT id FROM orders WHERE customer_id IS NULL"},
                None,
                1,
            ),
            ("freshness_pass", "fresh_orders", CheckType.FRESHNESS, "created_at", {"max_age_minutes": 60}, None, 0),
            (
                "freshness_stale_fail",
                "stale_orders",
                CheckType.FRESHNESS,
                "created_at",
                {"max_age_minutes": 60},
                None,
                1,
            ),
            # An empty table and an all-null column both leave the newest timestamp undefined. Freshness
            # has to fail there: comparing null to the threshold would pass the dead pipeline it exists
            # to catch.
            (
                "freshness_empty_fail",
                "empty_orders",
                CheckType.FRESHNESS,
                "created_at",
                {"max_age_minutes": 60},
                None,
                1,
            ),
            (
                "freshness_all_null_fail",
                "null_ts_orders",
                CheckType.FRESHNESS,
                "created_at",
                {"max_age_minutes": 60},
                None,
                1,
            ),
        ]
    )
    def test_failure_count_matches_the_data(
        self, _name, view_name, check_type, column_name, config, related_view, expected_failure_count
    ) -> None:
        merged_config = config if config is not None else self._relationships_config()
        compiled = self._compile(view_name, check_type, column_name, merged_config, related_view)

        assert self._execute(compiled.query).results[0][0] == expected_failure_count

    def test_row_count_observes_the_true_count(self) -> None:
        # row_count is the one BOUNDS check: it emits only observed_value, and the bound comparison is
        # the runner's job. What has to be right here is that the count it hands the runner is real.
        compiled = self._compile("orders", CheckType.ROW_COUNT, "", {"min": 1, "max": 10})

        assert self._execute(compiled.query).results[0][0] == 4

    @parameterized.expand(
        [
            ("not_null", CheckType.NOT_NULL, "customer_id", {}, None, _NULL_CUSTOMER_ROW),
            (
                "accepted_values",
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid", "refunded"]},
                None,
                _UNMATCHED_CUSTOMER_ROW,
            ),
            ("relationships", CheckType.RELATIONSHIPS, "customer_id", None, "customers", _UNMATCHED_CUSTOMER_ROW),
        ]
    )
    def test_the_stored_query_returns_the_offending_row(
        self, _name, check_type, column_name, config, related_view, expected_row
    ) -> None:
        # Failing rows are never persisted, so a human investigating re-runs this query by hand. It
        # has to come back with the data that broke, not a column of 1s.
        merged_config = config if config is not None else self._relationships_config()
        compiled = self._compile("orders", check_type, column_name, merged_config, related_view)

        response = self._execute(compiled.printed_failing_rows_query)

        assert [dict(zip(response.columns, row)) for row in response.results] == [expected_row]
