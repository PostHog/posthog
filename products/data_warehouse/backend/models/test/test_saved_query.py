from datetime import timedelta
from types import SimpleNamespace

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db.models.query import QuerySet as DjangoQuerySet

from parameterized import parameterized

from posthog.schema import CachedHogQLQueryResponse, HogQLQuery

from posthog import redis
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import AccessMethod, Feature, Product, tags_context
from posthog.constants import AvailableFeature
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode

from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


class TestRevertMaterialization(BaseTest):
    """Tests for DataWarehouseSavedQuery.revert_materialization.

    The method runs three DB operations (table soft-delete, saved_query save,
    model paths delete) inside one transaction. If any of them fails, every
    piece of state must be left as it was, so the next retry can converge on a
    consistent state.
    """

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
        DataWarehouseModelPath.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            path=["posthog_events", self.saved_query.id.hex],
        )

    def _assert_state_unchanged(self) -> None:
        """A rollback must leave every piece of state (saved_query, table, model paths)
        exactly as it was before revert_materialization was called."""
        self.saved_query.refresh_from_db()
        self.assertTrue(self.saved_query.is_materialized)
        self.assertEqual(self.saved_query.sync_frequency_interval, timedelta(hours=1))
        self.assertEqual(self.saved_query.status, DataWarehouseSavedQuery.Status.COMPLETED)
        self.assertIsNotNone(self.saved_query.table_id)

        self.table.refresh_from_db()
        self.assertFalse(self.table.deleted)

        self.assertTrue(DataWarehouseModelPath.objects.filter(team=self.team, saved_query=self.saved_query).exists())

    def test_state_cleared_when_all_operations_succeed(self):
        self.saved_query.revert_materialization()

        self.saved_query.refresh_from_db()
        self.assertFalse(self.saved_query.is_materialized)
        self.assertIsNone(self.saved_query.sync_frequency_interval)
        self.assertIsNone(self.saved_query.status)
        self.assertIsNone(self.saved_query.table_id)

        self.table.refresh_from_db()
        self.assertTrue(self.table.deleted)

        self.assertFalse(DataWarehouseModelPath.objects.filter(team=self.team, saved_query=self.saved_query).exists())

    def test_rollback_when_model_path_delete_raises(self):
        """The last DB op raising must roll back the table soft_delete and the
        saved_query save that ran earlier in the same block."""
        original_delete = DjangoQuerySet.delete

        def failing_delete(self_qs, *args, **kwargs):
            # Only raise for DataWarehouseModelPath querysets so that test fixture
            # cleanup and any unrelated delete calls still work normally.
            if self_qs.model is DataWarehouseModelPath:
                raise RuntimeError("model path delete failed")
            return original_delete(self_qs, *args, **kwargs)

        with patch.object(DjangoQuerySet, "delete", failing_delete):
            with self.assertRaisesRegex(RuntimeError, "model path delete failed"):
                self.saved_query.revert_materialization()

        self._assert_state_unchanged()


class TestGetColumnsQueryTagging(BaseTest):
    """get_columns infers types by executing the query via sync_execute, which requires product +
    feature query tags (enforced as a hard error in DEBUG). Untagged, view creation over any table —
    including ai_events — fails with UntaggedQueryError. The inference query must be tagged."""

    @patch("posthog.hogql.query.execute_hogql_query")
    def test_get_columns_tags_the_inference_query(self, mock_execute_hogql_query):
        from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags

        captured: dict[str, object] = {}

        def _capture(*args, **kwargs):
            tags = get_query_tags()
            captured["product"] = tags.product
            captured["feature"] = tags.feature
            return SimpleNamespace(types=[("trace_id", "String")])

        mock_execute_hogql_query.side_effect = _capture

        saved_query = DataWarehouseSavedQuery(
            team=self.team,
            name="my_view",
            query={"query": "SELECT trace_id FROM posthog.ai_events"},
        )
        columns = saved_query.get_columns()

        assert captured["product"] == Product.WAREHOUSE
        assert captured["feature"] == Feature.DATA_MODELING
        assert columns == {"trace_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}}


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
                patch("posthog.hogql.query.sync_execute", return_value=([], column_types)),
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

        with patch("posthog.hogql.query.sync_execute", return_value=([], column_types)):
            columns = saved_query.get_columns(user=self.user)
        assert columns["value"]["clickhouse"] == "UInt8"


class TestGetColumnsReadsNoRows(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("aggregation", "SELECT uuid, count() AS n FROM events GROUP BY uuid", {"uuid": "UUID", "n": "UInt64"}),
            (
                "existing_limit_and_offset",
                "SELECT uuid, count() AS n FROM events GROUP BY uuid LIMIT 5 OFFSET 2",
                {"uuid": "UUID", "n": "UInt64"},
            ),
            (
                "union_all",
                "SELECT event AS name FROM events UNION ALL SELECT distinct_id AS name FROM events LIMIT 3",
                {"name": "String"},
            ),
            (
                "in_subquery",
                "SELECT event FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE event = 'sign up')",
                {"event": "String"},
            ),
        ]
    )
    def test_infers_types_without_reading_rows(self, _name: str, sql: str, expected_types: dict[str, str]) -> None:
        saved_query = DataWarehouseSavedQuery(team=self.team, name="my_view", query={"query": sql})

        with self.capture_select_queries() as queries:
            columns = saved_query.get_columns(user=self.user)

        assert {name: column["clickhouse"] for name, column in columns.items()} == expected_types
        assert len(queries) == 1
        assert queries[0].count("LIMIT 0") == queries[0].count("SELECT")
        assert "OFFSET" not in queries[0]

    def test_keeps_the_rows_of_a_scalar_subquery(self) -> None:
        saved_query = DataWarehouseSavedQuery(
            team=self.team,
            name="my_view",
            query={"query": "SELECT event FROM events WHERE timestamp > (SELECT min(timestamp) FROM events)"},
        )

        with self.capture_select_queries() as queries:
            columns = saved_query.get_columns(user=self.user)

        assert columns["event"]["clickhouse"] == "String"
        assert queries[0].count("SELECT") == 2
        assert queries[0].count("LIMIT 0") == 1
