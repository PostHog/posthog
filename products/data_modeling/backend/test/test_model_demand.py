from collections.abc import Callable
from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import DEFAULT, patch

from django.db import OperationalError, connection, transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.redis import get_client

from products.data_modeling.backend.logic.demand import SHARD_COUNT, ModelDemand
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


class TestModelDemand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.clock = time_machine.travel(self.now, tick=False)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="demand_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            columns={"id": "Int64"},
        )
        node = sync_saved_query_to_dag(self.view, reconcile=False)
        assert node is not None
        self.node = node
        self.redis_client = get_client()
        self.key = ModelDemand.buffer_key(self.team.pk % SHARD_COUNT)

    def executor(self, query: str, context: HogQLContext | None = None) -> HogQLQueryExecutor:
        return HogQLQueryExecutor(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(useMaterializedViews=True),
            context=context or HogQLContext(team=self.team),
        )

    @parameterized.expand([(False,), (True,)])
    def test_query_attempt_records_demand_but_compilation_does_not(self, fails: bool) -> None:
        executor = self.executor("SELECT a.id FROM demand_view a JOIN demand_view b ON a.id = b.id")
        executor.generate_clickhouse_sql()
        self.assertEqual(self.redis_client.zcard(self.key), 0)

        with tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY):
            with patch("posthog.hogql.query.sync_execute", return_value=([[1]], [("id", "Int64")])) as execute:
                if fails:
                    execute.side_effect = RuntimeError("query failed")
                    with self.assertRaisesRegex(RuntimeError, "query failed"):
                        executor.execute()
                else:
                    self.assertEqual(executor.execute().results, [[1]])

        self.assertEqual(self.redis_client.zcard(self.key), 1)
        self.node.refresh_from_db()
        self.assertIsNone(self.node.last_demand_at)
        ModelDemand.flush()
        self.node.refresh_from_db()
        self.assertEqual(self.node.last_demand_at, self.now)
        self.assertEqual(self.redis_client.zcard(self.key), 0)

    @parameterized.expand(
        [(Feature.DATA_MODELING,), (Feature.SCHEMA_INTROSPECTION,), (Feature.ENRICHMENT,), (Feature.CACHE_WARMUP,)]
    )
    def test_background_execution_does_not_record_demand(self, feature: Feature) -> None:
        with (
            tags_context(product=Product.WAREHOUSE, feature=feature),
            patch("posthog.hogql.query.sync_execute", return_value=([[1]], [("id", "Int64")])),
        ):
            self.executor("SELECT id FROM demand_view").execute()
        self.assertEqual(self.redis_client.zcard(self.key), 0)

    def test_materialized_query_propagates_through_stored_dependencies(self) -> None:
        credentials = DataWarehouseCredential.objects.create(team=self.team, access_key="fake", access_secret="fake")
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="demand_matview",
            format="Parquet",
            credential=credentials,
            url_pattern="https://example.com/data/*.parquet",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True}},
        )
        matview = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="demand_matview",
            query={"kind": "HogQLQuery", "query": "SELECT id FROM demand_view"},
            columns={"id": "Int64"},
            table=table,
            is_materialized=True,
        )
        materialized_node = sync_saved_query_to_dag(matview, reconcile=False)
        assert materialized_node is not None
        with (
            tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY),
            patch("posthog.hogql.query.sync_execute", return_value=([[1]], [("id", "Int64")])),
        ):
            executor = self.executor("SELECT id FROM demand_matview")
            executor.execute()
        self.assertEqual(executor.context.referenced_saved_query_ids, {str(matview.pk)})
        ModelDemand.flush()
        self.node.refresh_from_db()
        materialized_node.refresh_from_db()
        self.assertEqual(self.node.last_demand_at, self.now)
        self.assertEqual(materialized_node.last_demand_at, self.now)

    def test_propagation_covers_cross_dag_references_and_preserves_tenant_scope(self) -> None:
        other_dag = DAG.objects.create(team=self.team, name="Another DAG")
        duplicate = Node.objects.create(team=self.team, dag=other_dag, saved_query=self.view, type=NodeType.VIEW)
        source = Node.objects.create(team=self.team, dag=other_dag, name="events", type=NodeType.TABLE)
        Edge.objects.create(team=self.team, dag=other_dag, source=source, target=duplicate)
        reference = Node.objects.create(
            team=self.team,
            dag=self.node.dag,
            name="managed_reference",
            type=NodeType.TABLE,
            properties={"origin": "cross_dag_view", "saved_query_id": str(self.view.pk)},
        )
        consumer = DataWarehouseSavedQuery.objects.create(team=self.team, name="consumer", query={"query": "SELECT 1"})
        consumer_node = Node.objects.create(
            team=self.team, dag=self.node.dag, saved_query=consumer, type=NodeType.MAT_VIEW
        )
        Edge.objects.create(team=self.team, dag=self.node.dag, source=reference, target=consumer_node)
        untouched = Node.objects.create(team=self.team, dag=self.node.dag, name="untouched", type=NodeType.TABLE)

        ModelDemand.record(self.team.pk + 1, [str(consumer.pk)])
        ModelDemand.flush()
        self.assertFalse(Node.objects.filter(team_id=self.team.pk, last_demand_at__isnull=False).exists())

        ModelDemand.record(self.team.pk, [str(consumer.pk)])
        ModelDemand.flush()
        for node in [self.node, duplicate, source, reference, consumer_node]:
            node.refresh_from_db()
            self.assertEqual(node.last_demand_at, self.now)
        untouched.refresh_from_db()
        self.assertIsNone(untouched.last_demand_at)

    def test_flush_retains_concurrent_demand_and_never_regresses_timestamp(self) -> None:
        ModelDemand.record(self.team.pk, [str(self.view.pk)])
        original_eval = self.redis_client.eval
        later = self.now + timedelta(minutes=1)

        def record_before_acknowledgement(script: str, numkeys: int, *args: bytes | str | int | float) -> object:
            with time_machine.travel(later, tick=False):
                ModelDemand.record(self.team.pk, [str(self.view.pk)])
            return original_eval(script, numkeys, *args)

        with patch.object(self.redis_client, "eval", side_effect=record_before_acknowledgement):
            ModelDemand.flush()
        self.node.refresh_from_db()
        self.assertEqual(self.node.last_demand_at, self.now)
        self.assertEqual(self.redis_client.zcard(self.key), 1)
        ModelDemand.record(self.team.pk, [str(self.view.pk)])
        self.assertEqual(self.redis_client.zscore(self.key, f"{self.team.pk}:{self.view.pk}"), later.timestamp())
        ModelDemand.flush()
        ModelDemand.record(self.team.pk, [str(self.view.pk)])
        ModelDemand.flush()
        self.node.refresh_from_db()
        self.assertEqual(self.node.last_demand_at, later)
        self.assertEqual(self.redis_client.zcard(self.key), 0)

    def test_failed_persistence_leaves_demand_for_retry(self) -> None:
        ModelDemand.record(self.team.pk, [str(self.view.pk)])
        with connection.execute_wrapper(self.fail_database_write):
            with self.assertRaisesRegex(OperationalError, "database unavailable"):
                with transaction.atomic():
                    ModelDemand.flush()
        self.assertEqual(self.redis_client.zcard(self.key), 1)
        ModelDemand.flush()
        self.node.refresh_from_db()
        self.assertEqual(self.node.last_demand_at, self.now)

    @staticmethod
    def fail_database_write(
        execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
    ) -> object:
        if sql.startswith('UPDATE "posthog_datamodelingnode"'):
            raise OperationalError("database unavailable")
        return execute(sql, params, many, context)

    @parameterized.expand(["persist", "acknowledge"])
    def test_one_team_failure_does_not_withhold_the_other_teams(self, failure_stage: str) -> None:
        stalled_team_id = self.team.pk + SHARD_COUNT
        # The older timestamp puts the stalled team first in the shard's flush order.
        with time_machine.travel(self.now - timedelta(minutes=1), tick=False):
            ModelDemand.record(stalled_team_id, [str(self.view.pk)])
        ModelDemand.record(self.team.pk, [str(self.view.pk)])
        failing_operation = (
            patch.object(
                ModelDemand,
                "persist_team",
                side_effect=[OperationalError("database unavailable"), DEFAULT],
                wraps=ModelDemand.persist_team,
            )
            if failure_stage == "persist"
            else patch.object(
                self.redis_client,
                "eval",
                side_effect=[ConnectionError("redis unavailable"), DEFAULT],
                wraps=self.redis_client.eval,
            )
        )

        with failing_operation:
            with self.assertRaisesRegex((OperationalError, ConnectionError), "unavailable"):
                ModelDemand.flush()

        self.node.refresh_from_db()
        self.assertEqual(self.node.last_demand_at, self.now)
        self.assertEqual(self.redis_client.zrange(self.key, 0, -1), [f"{stalled_team_id}:{self.view.pk}".encode()])
        ModelDemand.flush()
        self.assertEqual(self.redis_client.zcard(self.key), 0)

    def test_redis_failure_does_not_fail_the_query(self) -> None:
        with (
            tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY),
            patch.object(self.redis_client, "zadd", side_effect=ConnectionError("redis unavailable")),
            patch("posthog.hogql.query.sync_execute", return_value=([[1]], [("id", "Int64")])),
        ):
            self.assertEqual(self.executor("SELECT id FROM demand_view").execute().results, [[1]])

    def test_context_reuse_and_cte_shadowing_do_not_replay_demand(self) -> None:
        context = HogQLContext(team=self.team, database=Database.create_for(team=self.team))
        self.executor("SELECT id FROM demand_view", context).generate_clickhouse_sql()
        with (
            tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY),
            patch("posthog.hogql.query.sync_execute", return_value=([[2]], [("id", "Int64")])),
        ):
            self.executor("WITH demand_view AS (SELECT 2 AS id) SELECT id FROM demand_view", context).execute()
        self.assertEqual(self.redis_client.zcard(self.key), 0)
