from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.schema import CachedHogQLQueryResponse, HogQLQuery

from posthog.hogql.database.models import DecimalDatabaseField
from posthog.hogql.query import execute_hogql_query

from posthog import redis
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import AccessMethod, Feature, Product, tags_context
from posthog.constants import AvailableFeature
from posthog.errors import CHQueryErrorS3Error, CHQueryErrorS3FileChangedDuringRead
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


class TestRevertMaterialization(BaseTest):
    def setUp(self):
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(
            access_key="test_key",
            access_secret="test_secret",
            team=self.team,
        )
        self.table = DataWarehouseTable.objects.create(
            name="stripe_charge",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/stripe_charge/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}},
        )
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            table=self.table,
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=1),
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

    def _assert_state_unchanged(self) -> None:
        self.saved_query.refresh_from_db()
        self.assertTrue(self.saved_query.is_materialized)
        self.assertEqual(self.saved_query.sync_frequency_interval, timedelta(hours=1))
        self.assertEqual(self.saved_query.status, DataWarehouseSavedQuery.Status.COMPLETED)
        self.assertIsNotNone(self.saved_query.table_id)

        self.table.refresh_from_db()
        self.assertFalse(self.table.deleted)

    def test_state_cleared_when_all_operations_succeed(self):
        self.saved_query.revert_materialization()

        self.saved_query.refresh_from_db()
        self.assertFalse(self.saved_query.is_materialized)
        self.assertIsNone(self.saved_query.sync_frequency_interval)
        self.assertIsNone(self.saved_query.status)
        self.assertIsNone(self.saved_query.table_id)

        self.table.refresh_from_db()
        self.assertTrue(self.table.deleted)

    def test_rollback_when_saved_query_save_raises(self):
        with patch.object(DataWarehouseSavedQuery, "save", side_effect=RuntimeError("saved query save failed")):
            with self.assertRaisesRegex(RuntimeError, "saved query save failed"):
                self.saved_query.revert_materialization()

        self._assert_state_unchanged()


class TestGetColumnsQueryTagging(BaseTest):
    """get_columns infers types by executing the query via sync_execute, which requires product +
    feature query tags (enforced as a hard error in DEBUG). Untagged, view creation over any table —
    including ai_events — fails with UntaggedQueryError. The inference query must be tagged."""

    @patch("products.data_modeling.backend.logic.describe_columns.sync_execute")
    def test_get_columns_tags_the_inference_query(self, mock_sync_execute):
        from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags

        captured: dict[str, object] = {}

        def _capture(*args, **kwargs):
            tags = get_query_tags()
            captured["product"] = tags.product
            captured["feature"] = tags.feature
            captured["query_type"] = tags.query_type
            return [("trace_id", "String")]

        mock_sync_execute.side_effect = _capture

        saved_query = DataWarehouseSavedQuery(
            team=self.team,
            name="my_view",
            query={"query": "SELECT trace_id FROM posthog.ai_events"},
        )
        columns = saved_query.get_columns()

        assert captured["product"] == Product.WAREHOUSE
        assert captured["feature"] == Feature.DATA_MODELING
        assert captured["query_type"] == "HogQLQuery"
        assert columns == {"trace_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}}


class TestGetColumnsRetriesTransientS3Errors(BaseTest):
    @parameterized.expand(
        [
            ("file_changed", CHQueryErrorS3FileChangedDuringRead("file changed during read", code=1011)),
            ("s3_error", CHQueryErrorS3Error("S3 error occurred.", code=499)),
        ]
    )
    @patch("products.data_modeling.backend.logic.describe_columns.sleep")
    def test_describes_again_after_one_transient_s3_error(self, _name: str, error: Exception, _sleep) -> None:
        saved_query = DataWarehouseSavedQuery(team=self.team, name="my_view", query={"query": "SELECT 1 AS value"})

        with patch(
            "products.data_modeling.backend.logic.describe_columns.sync_execute",
            side_effect=[error, [("value", "UInt8")]],
        ):
            columns = saved_query.get_columns(user=self.user)

        assert columns["value"]["clickhouse"] == "UInt8"


class TestGetColumnsConcurrency(BaseTest):
    @parameterized.expand(
        [
            ("browser", None, False),
            ("oauth", AccessMethod.OAUTH, False),
            ("api_key", AccessMethod.PERSONAL_API_KEY, True),
        ]
    )
    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_shares_the_query_runner_organization_limit(
        self, _name: str, access_method: AccessMethod | None, is_api_key: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_APP_QUERY_CONCURRENCY_LIMIT, "limit": 1}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.addCleanup(redis.get_client().delete, f"org_app_concurrency_limit:{self.organization.id}")
        saved_query = DataWarehouseSavedQuery(team=self.team, name="my_view", query={"query": "SELECT 1 AS value"})
        column_types = [("value", "UInt8")]

        def infer_while_query_runs(*args: object, **kwargs: object) -> tuple[list[tuple[int]], list[tuple[str, str]]]:
            with (
                tags_context(access_method=access_method),
                patch("products.data_modeling.backend.logic.describe_columns.sync_execute", return_value=column_types),
            ):
                if is_api_key:
                    columns = saved_query.get_columns(user=self.user)
                    assert columns["value"]["clickhouse"] == "UInt8"
                else:
                    with self.assertRaises(ConcurrencyLimitExceeded):
                        saved_query.get_columns(user=self.user)
            return [(1,)], column_types

        runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1 AS value"), team=self.team, user=self.user)
        with (
            tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY, access_method=None),
            patch("posthog.hogql.query.sync_execute", side_effect=infer_while_query_runs),
        ):
            result = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(result, CachedHogQLQueryResponse)
        assert result.results == [(1,)]

        with patch("products.data_modeling.backend.logic.describe_columns.sync_execute", return_value=column_types):
            columns = saved_query.get_columns(user=self.user)
        assert columns["value"]["clickhouse"] == "UInt8"


class TestGetColumnsDescribesTheQuery(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("aggregation", "SELECT uuid, count() AS n FROM events GROUP BY uuid"),
            ("union_all", "SELECT event AS name FROM events UNION ALL SELECT distinct_id AS name FROM events"),
            (
                "in_subquery",
                "SELECT event FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE event = 'sign up')",
            ),
            ("scalar_subquery", "SELECT event FROM events WHERE timestamp > (SELECT min(timestamp) FROM events)"),
            ("person_join", "SELECT event, person_id, person.properties.email AS email FROM events"),
            (
                "join",
                "SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id",
            ),
            ("cte", "WITH signups AS (SELECT distinct_id, timestamp FROM events) SELECT * FROM signups"),
            ("columns_matcher", "SELECT COLUMNS('^(event|distinct_id)$') FROM events"),
            ("nested_view", "SELECT name, n FROM inner_view"),
            (
                "global_in_output_name_with_a_percent_sign",
                "SELECT event IN (SELECT event FROM events WHERE event LIKE '%view%') FROM events",
            ),
            (
                "global_in_inside_an_output_column",
                "SELECT countIf(event IN (SELECT key FROM groups LIMIT 5)) FROM events",
            ),
        ]
    )
    def test_types_match_running_the_query(self, _name: str, sql: str) -> None:
        inner_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="inner_view",
            query={"query": "SELECT event AS name, count() AS n FROM events GROUP BY event"},
        )
        inner_view.set_columns(inner_view.get_columns(user=self.user))
        inner_view.save()
        saved_query = DataWarehouseSavedQuery(team=self.team, name="my_view", query={"query": sql})

        executed = execute_hogql_query(sql, team=self.team, user=self.user)

        with self.capture_queries(lambda query: True) as queries:
            columns = saved_query.get_columns(user=self.user)

        assert {name: column["clickhouse"] for name, column in columns.items()} == dict(executed.types or [])
        assert len(queries) == 1
        assert "DESCRIBE TABLE" in queries[0]
        assert "globalIn" not in queries[0]

    def test_a_jev_view_describes_its_model_results_without_calling_the_model(self) -> None:
        sql = (
            "SELECT text, jev(text, 'Is this a refund request?') AS is_refund "
            "FROM (SELECT arrayJoin(['refund me', 'hi']) AS text) "
            "WHERE text NOT IN (SELECT event FROM events)"
        )
        saved_query = DataWarehouseSavedQuery(team=self.team, name="my_view", query={"query": sql})

        with override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key"):
            with patch("httpx.AsyncClient.post", side_effect=_refund_gateway_response):
                executed = execute_hogql_query(sql, team=self.team, user=self.user)
            with (
                patch("httpx.AsyncClient.post", side_effect=AssertionError("called the model")),
                self.capture_select_queries() as jev_source_queries,
            ):
                columns = saved_query.get_columns(user=self.user)

        assert {name: column["clickhouse"] for name, column in columns.items()} == dict(executed.types or [])
        assert [query.count("LIMIT 0") for query in jev_source_queries] == [2]


def _refund_gateway_response(_url: str, *, json: dict, headers: dict) -> httpx.Response:
    answers = {
        name: {"type": "noul", "noul": 0.9 if "refund" in json["state"][name] else 0.1} for name in json["questions"]
    }
    return httpx.Response(200, json={"model": "jevk5-0.2", "answers": answers, "usage": {"input_tokens": 10}})


class TestHogqlFieldsKeepDecimalScale(SimpleTestCase):
    def test_decimal_column_keeps_its_scale(self) -> None:
        saved_query = DataWarehouseSavedQuery(
            columns={"amount": {"clickhouse": "Nullable(Decimal(38, 8))", "hogql": "DecimalDatabaseField"}}
        )

        field = saved_query.hogql_fields()["amount"]

        assert isinstance(field, DecimalDatabaseField)
        assert field.scale == 8
