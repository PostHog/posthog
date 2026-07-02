from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.models import StringDatabaseField, Table
from posthog.hogql.database.schema.table_descriptions import TableDescriptions

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.data_modeling.backend.facade.models import (
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable
from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation


class TestTableDescriptions(APIBaseTest):
    def _warehouse_table(
        self, *, name: str = "orders", team: Team | None = None, columns: tuple[str, ...] = ("id",)
    ) -> DataWarehouseTable:
        team = team or self.team
        credential = DataWarehouseCredential.objects.create(access_key="x", access_secret="x", team=team)
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            columns={
                c: {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True} for c in columns
            },
        )

    def _view(self, *, name: str = "orders_view", team: Team | None = None) -> DataWarehouseSavedQuery:
        team = team or self.team
        return DataWarehouseSavedQuery.objects.create(
            team=team,
            name=name,
            query={"query": "SELECT 1 AS amount"},
            columns={"amount": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

    def test_resolves_warehouse_descriptions_by_table_id(self):
        # A synced table's catalog name differs from its model name, so annotations must resolve by table
        # UUID, not name — keying by name silently dropped every annotation in production. The e2e catalog
        # tests use a table whose name matches, so they wouldn't catch a name-keyed regression; this does.
        table = self._warehouse_table()
        with team_scope(self.team.id, canonical=True):
            WarehouseColumnAnnotation.objects.create(
                team=self.team,
                table=table,
                column_name="",
                description="All orders placed by customers.",
                description_source=WarehouseColumnAnnotation.DescriptionSource.CANONICAL,
            )
            WarehouseColumnAnnotation.objects.create(
                team=self.team,
                table=table,
                column_name="id",
                description="Unique order identifier.",
                description_source=WarehouseColumnAnnotation.DescriptionSource.USER_EDITED,
            )
        hogql_table = table.hogql_definition()
        resolver = TableDescriptions.load(self.team.id)
        assert resolver.for_table(hogql_table) == "All orders placed by customers."
        assert resolver.for_column(hogql_table, "id", hogql_table.fields["id"]) == "Unique order identifier."

    def test_resolves_view_descriptions_by_saved_query_id(self):
        view = self._view()
        with team_scope(self.team.id, canonical=True):
            DataWarehouseSavedQueryColumnAnnotation.objects.create(
                team=self.team,
                saved_query=view,
                column_name="",
                description="Revenue per order.",
                description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.USER_EDITED,
            )
            DataWarehouseSavedQueryColumnAnnotation.objects.create(
                team=self.team,
                saved_query=view,
                column_name="amount",
                description="Order revenue in cents.",
                description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.USER_EDITED,
            )
        hogql_view = view.hogql_definition()
        resolver = TableDescriptions.load(self.team.id)
        assert resolver.for_table(hogql_view) == "Revenue per order."
        assert resolver.for_column(hogql_view, "amount", hogql_view.fields["amount"]) == "Order revenue in cents."

    def test_resolves_materialized_view_descriptions_via_backing_table(self):
        # A materialized view queried in materialized mode resolves to its single backing (output)
        # table, so `hogql_definition` returns a warehouse table keyed by the backing table's id, not
        # the SavedQuery. The view's own annotations must still resolve via the backing->view mapping.
        backing = self._warehouse_table(name="revenue_view_backing", columns=("amount",))
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="revenue_view",
            query={"query": "SELECT 1 AS amount"},
            columns={"amount": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True}},
            table=backing,
            is_materialized=True,
        )
        with team_scope(self.team.id, canonical=True):
            DataWarehouseSavedQueryColumnAnnotation.objects.create(
                team=self.team,
                saved_query=view,
                column_name="amount",
                description="Order revenue in cents.",
                description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.USER_EDITED,
            )
        # Materialized mode swaps the view for its backing warehouse table object.
        backing_hogql = view.hogql_definition(HogQLQueryModifiers(useMaterializedViews=True))
        resolver = TableDescriptions.load(self.team.id)
        assert resolver.for_column(backing_hogql, "amount", backing_hogql.fields["amount"]) == "Order revenue in cents."

    def test_resolves_static_field_description_for_native_tables(self):
        # Native tables carry their descriptions on the field objects, not in an annotation model.
        # Both consumers (information_schema and read_data) rely on the resolver surfacing them.
        resolver = TableDescriptions({}, {}, {})
        field = StringDatabaseField(name="ts", description="When the event occurred.")
        table = Table(fields={"ts": field}, name="events", description="Every analytics event.")

        assert resolver.for_table(table) == "Every analytics event."
        assert resolver.for_column(table, "ts", field) == "When the event occurred."

    @parameterized.expand(["warehouse", "view"])
    def test_load_does_not_leak_other_teams_descriptions(self, kind: str):
        # Annotations are team-scoped via TeamScopedManager; lock that in so a future switch to
        # `.unscoped()` can't leak another team's descriptions into a resolver loaded for this team.
        other = Team.objects.create(organization=self.organization, name="other")
        hogql_table: Table
        if kind == "warehouse":
            table = self._warehouse_table(team=other)
            with team_scope(other.id, canonical=True):
                WarehouseColumnAnnotation.objects.create(
                    team=other,
                    table=table,
                    column_name="",
                    description="Other team's private table.",
                    description_source=WarehouseColumnAnnotation.DescriptionSource.USER_EDITED,
                )
            hogql_table = table.hogql_definition()
        else:
            view = self._view(team=other)
            with team_scope(other.id, canonical=True):
                DataWarehouseSavedQueryColumnAnnotation.objects.create(
                    team=other,
                    saved_query=view,
                    column_name="",
                    description="Other team's private view.",
                    description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.USER_EDITED,
                )
            hogql_table = view.hogql_definition()

        resolver = TableDescriptions.load(self.team.id)
        assert resolver.for_table(hogql_table) is None
