from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import CheckType, SubjectType
from products.data_quality.backend.logic.compiler import compile_check
from products.data_quality.backend.logic.contracts import SubjectRef

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


class TestCompiledCheckExecution(ClickhouseTestMixin, APIBaseTest):
    def _view(self, name: str, query: str, columns: dict) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": query}, columns=columns
        )

    def setUp(self) -> None:
        super().setUp()
        self._view("orders", _ORDERS_QUERY, {"id": _INT, "customer_id": _STRING, "status": _STRING})
        self._view("customers", "SELECT 'c1' AS id UNION ALL SELECT 'c2'", {"id": _STRING})
        self._view("fresh_orders", "SELECT now() AS created_at", {"created_at": _DATETIME})
        self._view("stale_orders", "SELECT toDateTime('2000-01-01 00:00:00') AS created_at", {"created_at": _DATETIME})
        self._view("empty_orders", "SELECT now() AS created_at LIMIT 0", {"created_at": _DATETIME})
        self._view(
            "null_ts_orders",
            "SELECT nullIf(now(), now()) AS created_at UNION ALL SELECT nullIf(now(), now())",
            {"created_at": _DATETIME},
        )

    def _subject(self, view_name: str) -> SubjectRef:
        return SubjectRef(SubjectType.VIEW, str(uuid4()), view_name, view_name, exists=True)

    def _run(self, compiled) -> tuple:
        return execute_hogql_query(
            query=compiled.query,
            team=self.team,
            query_type="data_quality_check",
            bypass_warehouse_access_control=True,
        ).results[0]

    @parameterized.expand(
        [
            ("not_null_pass", "orders", CheckType.NOT_NULL, "status", {}, None, 0),
            ("not_null_fail", "orders", CheckType.NOT_NULL, "customer_id", {}, None, 1),
            ("unique_fail", "orders", CheckType.UNIQUE, "id", {}, None, 1),
            ("unique_pass", "orders", CheckType.UNIQUE, "customer_id", {}, None, 0),
            (
                "accepted_values_fail",
                "orders",
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid", "refunded"]},
                None,
                1,
            ),
            (
                "accepted_values_pass",
                "orders",
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid", "refunded", "shipped"]},
                None,
                0,
            ),
            ("relationships_fail", "orders", CheckType.RELATIONSHIPS, "customer_id", None, "customers", 1),
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
        related = self._subject(related_view) if related_view else None
        merged_config = config if config is not None else self._relationships_config()
        compiled = compile_check(
            check_type=check_type,
            subject=self._subject(view_name),
            column_name=column_name,
            config=merged_config,
            related_subject=related,
        )
        failure_count = self._run(compiled)[0]
        assert failure_count == expected_failure_count

    def _relationships_config(self) -> dict:
        return {"to_subject_type": "view", "to_subject_uuid": str(uuid4()), "to_column": "id"}

    def test_row_count_observes_the_true_count(self) -> None:
        # row_count is the one BOUNDS check: it emits only observed_value, and the bound comparison is
        # the runner's job. What has to be right here is that the count it hands the runner is real.
        compiled = compile_check(
            check_type=CheckType.ROW_COUNT,
            subject=self._subject("orders"),
            column_name="",
            config={"min": 1, "max": 10},
            related_subject=None,
        )
        observed_value = self._run(compiled)[0]
        assert observed_value == 4
