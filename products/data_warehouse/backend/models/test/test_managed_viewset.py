from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError

from posthog.schema import RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from products.data_modeling.backend.facade.models import (
    DAG,
    REVENUE_ANALYTICS_DAG_NAME,
    DataWarehouseManagedViewSet,
    DataWarehouseSavedQuery,
    Edge,
    Node,
    NodeType,
)
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.sources import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

STRIPE_SCHEMA_NAMES = [
    STRIPE_CHARGE_RESOURCE_NAME,
    STRIPE_CUSTOMER_RESOURCE_NAME,
    STRIPE_INVOICE_RESOURCE_NAME,
    STRIPE_PRODUCT_RESOURCE_NAME,
    STRIPE_SUBSCRIPTION_RESOURCE_NAME,
]

DUMMY_COLUMNS = {"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}}
SCHEDULE_MATERIALIZATION = (
    "products.data_modeling.backend.models.datawarehouse_saved_query.DataWarehouseSavedQuery.schedule_materialization"
)


class TestDataWarehouseManagedViewSetModel(BaseTest):
    def setUp(self):
        super().setUp()

        # Set up revenue analytics events configuration
        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName="purchase",
                revenueProperty="amount",
                currencyAwareDecimal=True,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
            ),
            RevenueAnalyticsEventItem(
                eventName="subscription_charge",
                revenueProperty="price",
                currencyAwareDecimal=False,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(property="currency"),
                productProperty="product_id",
            ),
        ]
        self.team.revenue_analytics_config.save()

    def test_sync_views_reconciles_dag_schedules_once(self):
        # sync_views touches N views; reconciling per view would issue N redundant
        # Temporal converges for the one managed DAG
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        with (
            patch(SCHEDULE_MATERIALIZATION),
            patch(
                "products.data_modeling.backend.models.datawarehouse_managed_viewset.maybe_reconcile_dag"
            ) as reconcile,
        ):
            managed_viewset.sync_views()

        reconcile.assert_called_once()

    def test_sync_views_creates_views(self):
        """Test that enabling managed viewset creates the expected views"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Call sync_views to create the views
        managed_viewset.sync_views()

        # Check that views were created
        views = DataWarehouseSavedQuery.objects.filter(
            team=self.team,
            managed_viewset__kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        ).exclude(deleted=True)

        # Should have views for each event (purchase, subscription_charge) and each view type
        # Each event should generate 6 view types: customer, charge, subscription, revenue_item, product, mrr
        expected_view_count = 2 * 6  # 2 events * 6 types
        self.assertGreaterEqual(views.count(), expected_view_count)

        # Check that views have the expected structure
        for view in views:
            self.assertTrue(view.is_materialized)
            self.assertIsNotNone(view.query)
            self.assertIsNotNone(view.columns)
            self.assertIsNotNone(view.external_tables)
            self.assertIn("HogQLQuery", view.query.get("kind", ""))  # type: ignore

        expected_view_names = sorted(
            [
                "revenue_analytics.events.purchase.charge_events_revenue_view",
                "revenue_analytics.events.purchase.customer_events_revenue_view",
                "revenue_analytics.events.purchase.mrr_events_revenue_view",
                "revenue_analytics.events.purchase.revenue_item_events_revenue_view",
                "revenue_analytics.events.purchase.product_events_revenue_view",
                "revenue_analytics.events.purchase.subscription_events_revenue_view",
                "revenue_analytics.events.subscription_charge.charge_events_revenue_view",
                "revenue_analytics.events.subscription_charge.customer_events_revenue_view",
                "revenue_analytics.events.subscription_charge.mrr_events_revenue_view",
                "revenue_analytics.events.subscription_charge.product_events_revenue_view",
                "revenue_analytics.events.subscription_charge.revenue_item_events_revenue_view",
                "revenue_analytics.events.subscription_charge.subscription_events_revenue_view",
            ]
        )

        self.assertEqual(sorted([view.name for view in views]), expected_view_names)

    def test_sync_views_updates_existing_views(self):
        """Test that sync_views updates query and columns for existing views"""
        # First, create a managed viewset and some views
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Create a view with old query/columns
        old_query = {"kind": "HogQLQuery", "query": "SELECT 1 as old_column"}
        old_columns = {"old_column": {"hogql": "String", "clickhouse": "String", "valid": True}}

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="revenue_analytics.events.purchase.customer_events_revenue_view",
            query=old_query,
            columns=old_columns,
            managed_viewset=managed_viewset,
            is_materialized=True,
        )

        # Now call sync_views
        managed_viewset.sync_views()

        # Check that the view was updated
        saved_query.refresh_from_db()
        self.assertNotEqual(saved_query.query, old_query)
        self.assertNotEqual(saved_query.columns, old_columns)
        self.assertIsNotNone(saved_query.external_tables)  # Was unset, guarantee we've set it
        self.assertIn("HogQLQuery", saved_query.query.get("kind", ""))  # type: ignore

    def test_sync_views_places_views_in_revenue_analytics_dag(self):
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )
        managed_viewset.sync_views()

        ra_dag = DAG.objects.filter(team=self.team, name=REVENUE_ANALYTICS_DAG_NAME).first()
        self.assertIsNotNone(ra_dag)

        views = DataWarehouseSavedQuery.objects.filter(team=self.team, managed_viewset=managed_viewset).exclude(
            deleted=True
        )
        node_sq_ids = set(
            Node.objects.filter(team=self.team, dag=ra_dag, saved_query__isnull=False).values_list(
                "saved_query_id", flat=True
            )
        )
        # every managed view is represented by a node in the Revenue Analytics DAG, and nowhere else
        for view in views:
            self.assertIn(view.id, node_sq_ids)
            other_dag_nodes = Node.objects.filter(team=self.team, saved_query=view).exclude(dag=ra_dag)
            self.assertFalse(other_dag_nodes.exists())

    def test_sync_views_removes_stale_default_dag_node(self):
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )
        managed_viewset.sync_views()
        sq = (
            DataWarehouseSavedQuery.objects.filter(team=self.team, managed_viewset=managed_viewset)
            .exclude(deleted=True)
            .first()
        )

        # simulate a legacy placement of this managed view in the Default DAG
        default_dag = DAG.get_or_create_default(self.team)
        Node.objects.get_or_create(team=self.team, saved_query=sq, dag=default_dag, defaults={"type": NodeType.VIEW})

        managed_viewset.sync_views()

        ra_dag = DAG.objects.get(team=self.team, name=REVENUE_ANALYTICS_DAG_NAME)
        self.assertTrue(Node.objects.filter(team=self.team, saved_query=sq, dag=ra_dag).exists())
        self.assertFalse(Node.objects.filter(team=self.team, saved_query=sq, dag=default_dag).exists())

    def test_sync_views_keeps_stale_node_with_dependent(self):
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )
        managed_viewset.sync_views()
        sq = (
            DataWarehouseSavedQuery.objects.filter(team=self.team, managed_viewset=managed_viewset)
            .exclude(deleted=True)
            .first()
        )

        default_dag = DAG.get_or_create_default(self.team)
        stale_node, _ = Node.objects.get_or_create(
            team=self.team, saved_query=sq, dag=default_dag, defaults={"type": NodeType.VIEW}
        )
        # a non-managed view in the Default DAG depends on the stale node (stale_node has an outgoing edge)
        dependent_sq = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="dependent_view", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        dependent_node = Node.objects.create(
            team=self.team, saved_query=dependent_sq, dag=default_dag, type=NodeType.VIEW
        )
        Edge.objects.create(team=self.team, dag=default_dag, source=stale_node, target=dependent_node)

        managed_viewset.sync_views()

        # the stale Default-DAG node is kept because a dependent still relies on it
        self.assertTrue(Node.objects.filter(id=stale_node.id).exists())

    def test_delete_with_views(self):
        """Test that delete_with_views properly deletes the managed viewset and marks views as deleted"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Create some views associated with the managed viewset
        view1 = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view_1",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )
        view2 = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view_2",
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )

        # Delete the managed viewset with its views
        managed_viewset.delete_with_views()

        # Check that the managed viewset is deleted
        self.assertFalse(DataWarehouseManagedViewSet.objects.filter(id=managed_viewset.id).exists())

        # Check that views are marked as deleted
        view1.refresh_from_db()
        view2.refresh_from_db()
        self.assertTrue(view1.deleted)
        self.assertTrue(view2.deleted)
        self.assertIsNotNone(view1.deleted_at)
        self.assertIsNotNone(view2.deleted_at)

    def test_managed_viewset_creation(self):
        """Test basic managed viewset creation"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        self.assertEqual(managed_viewset.team, self.team)
        self.assertEqual(managed_viewset.kind, DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)
        self.assertIsNotNone(managed_viewset.id)
        self.assertIsNotNone(managed_viewset.created_at)

    def test_managed_viewset_unique_constraint(self):
        """Test that managed viewset has unique constraint on team and kind"""
        # Create first managed viewset
        DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Try to create another with same team and kind - should raise IntegrityError
        with self.assertRaises(IntegrityError):
            DataWarehouseManagedViewSet.objects.create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )


class TestManagedViewSetSyncWithStripeSource(BaseTest):
    """Tests for sync_views behavior with a Stripe external data source.

    Covers the lifecycle where views start with empty queries (tables don't
    exist yet during initial sync) and transition to real queries after
    the Stripe sync completes and tables are created.
    """

    def setUp(self):
        super().setUp()

        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_stripe_1",
            connection_id="conn_1",
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.STRIPE,
        )
        self.credential = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        self.managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

    def _create_schemas_without_tables(self) -> list[ExternalDataSchema]:
        return [
            ExternalDataSchema.objects.create(
                team=self.team, name=name, source=self.source, table=None, should_sync=True
            )
            for name in STRIPE_SCHEMA_NAMES
        ]

    def _create_table_for_schema(self, schema: ExternalDataSchema) -> DataWarehouseTable:
        table = DataWarehouseTable.objects.create(
            name=f"stripe_{schema.name.lower()}",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=self.source,
            credential=self.credential,
            url_pattern=f"https://bucket.s3/{schema.name.lower()}/*",
            columns=DUMMY_COLUMNS,
        )
        schema.table = table
        schema.save()
        return table

    def _get_saved_queries(self) -> list[DataWarehouseSavedQuery]:
        return list(
            DataWarehouseSavedQuery.objects.filter(team=self.team, managed_viewset=self.managed_viewset).exclude(
                deleted=True
            )
        )

    def assertQueryIsEmpty(self, saved_query: DataWarehouseSavedQuery, msg: str | None = None) -> None:
        assert saved_query.query is not None
        query_str = saved_query.query.get("query", "")
        self.assertTrue("where false" in query_str.lower(), msg=msg)

    def assertQueryIsNotEmpty(self, saved_query: DataWarehouseSavedQuery, msg: str | None = None) -> None:
        assert saved_query.query is not None
        query_str = saved_query.query.get("query", "")
        self.assertFalse("where false" in query_str.lower(), msg=msg)

    @patch(SCHEDULE_MATERIALIZATION)
    def test_sync_views_produces_empty_queries_when_no_tables_exist(self, _):
        self._create_schemas_without_tables()
        self.managed_viewset.sync_views()

        saved_queries = self._get_saved_queries()
        self.assertEqual(len(saved_queries), 6)

        # MRR view references other saved queries (not tables directly),
        # so it always produces a non-empty query regardless of table state
        for query in saved_queries:
            if "mrr" in query.name:
                continue
            self.assertQueryIsEmpty(query, f"Expected empty query initially for {query.name}")

    @patch(SCHEDULE_MATERIALIZATION)
    def test_sync_views_produces_real_queries_after_tables_created(self, _):
        schemas = self._create_schemas_without_tables()

        self.managed_viewset.sync_views()
        for query in self._get_saved_queries():
            if "mrr" in query.name:
                continue
            self.assertQueryIsEmpty(query, f"Expected empty query initially for {query.name}")

        for schema in schemas:
            self._create_table_for_schema(schema)

        self.managed_viewset.sync_views()
        saved_queries = self._get_saved_queries()
        self.assertEqual(len(saved_queries), 6)
        for query in saved_queries:
            self.assertQueryIsNotEmpty(query, f"Expected not empty query after table creation for {query.name}")

    @patch(SCHEDULE_MATERIALIZATION)
    def test_sync_views_is_idempotent(self, _):
        schemas = self._create_schemas_without_tables()
        for schema in schemas:
            self._create_table_for_schema(schema)

        self.managed_viewset.sync_views()
        count_after_first = len(self._get_saved_queries())

        self.managed_viewset.sync_views()
        count_after_second = len(self._get_saved_queries())

        self.managed_viewset.sync_views()
        count_after_third = len(self._get_saved_queries())

        self.assertEqual(count_after_first, count_after_second)
        self.assertEqual(count_after_second, count_after_third)

    @patch(SCHEDULE_MATERIALIZATION)
    def test_partial_sync_only_creates_real_queries_for_available_tables(self, _):
        schemas = self._create_schemas_without_tables()
        charge_schema = next(s for s in schemas if s.name == STRIPE_CHARGE_RESOURCE_NAME)
        self._create_table_for_schema(charge_schema)

        self.managed_viewset.sync_views()

        saved_queries = self._get_saved_queries()
        charge_query = next(query for query in saved_queries if "charge" in query.name)
        customer_query = next(sq for sq in saved_queries if "customer" in sq.name)
        self.assertQueryIsNotEmpty(charge_query)
        self.assertQueryIsEmpty(customer_query)

    def test_sync_views_schedules_after_transaction_commits(self):
        """schedule_materialization must run AFTER the phase 1 transaction commits,
        so that row locks on posthog_datawarehousesavedquery are released before
        synchronous Temporal RPCs and DataWarehouseModelPath updates begin. If
        schedule_materialization were called from inside the transaction, only the
        current iteration's saved query would be visible at the call site; after the
        refactor, all persisted saved queries should be visible at every call site.
        """
        schemas = self._create_schemas_without_tables()
        for schema in schemas:
            self._create_table_for_schema(schema)

        expected_view_count = 6
        counts_observed_during_schedule: list[int] = []
        team = self.team
        managed_viewset = self.managed_viewset

        def capture_count(*args, **kwargs):
            count = (
                DataWarehouseSavedQuery.objects.filter(team=team, managed_viewset=managed_viewset)
                .exclude(deleted=True)
                .count()
            )
            counts_observed_during_schedule.append(count)

        with patch(SCHEDULE_MATERIALIZATION, side_effect=capture_count):
            self.managed_viewset.sync_views()

        self.assertEqual(len(counts_observed_during_schedule), expected_view_count)
        for count in counts_observed_during_schedule:
            self.assertEqual(
                count,
                expected_view_count,
                f"Expected all {expected_view_count} saved queries to be persisted when "
                f"schedule_materialization runs (phase 2 after commit), but saw count={count}. "
                f"This regression indicates schedule_materialization is being called from inside "
                f"the sync_views transaction.",
            )

    def test_sync_views_persists_db_changes_when_schedule_materialization_fails(self):
        """Phase 2 failures (schedule_materialization raising) must not roll back the
        phase 1 DB changes. Each view's schedule failure is isolated: the saved query
        row remains committed and the loop continues to the next view.
        """
        schemas = self._create_schemas_without_tables()
        for schema in schemas:
            self._create_table_for_schema(schema)

        with patch(SCHEDULE_MATERIALIZATION, side_effect=Exception("boom")):
            self.managed_viewset.sync_views()

        saved_queries = self._get_saved_queries()
        self.assertEqual(len(saved_queries), 6)
