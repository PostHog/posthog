from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.database.database import Database

from posthog.models.team import Team

from products.data_modeling.backend.facade import api as data_modeling_facade
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import SubjectType
from products.data_quality.backend.logic.subject_access import readable_subjects
from products.data_quality.backend.logic.subjects import resolve_subject
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class TestSubjectResolver(BaseTest):
    def _table(self, name: str = "stripe_customers") -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            team=self.team, name=name, format="Parquet", url_pattern="s3://bucket/x"
        )

    def _view(self, name: str = "revenue_view") -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(team=self.team, name=name, query={"kind": "HogQLQuery"})

    def test_resolves_a_table_to_its_queryable_name(self) -> None:
        table = self._table()
        resolved = resolve_subject(self.team.id, SubjectType.TABLE, table.id)
        assert resolved.exists
        assert resolved.queryable_name == "stripe_customers"

    def test_resolves_a_view_to_its_own_name_even_when_materialized(self) -> None:
        view = self._view()
        view.table = self._table("materialized_backing_table")
        view.save()

        resolved = resolve_subject(self.team.id, SubjectType.VIEW, view.id)
        assert resolved.queryable_name == "revenue_view"

    @parameterized.expand([(SubjectType.TABLE,), (SubjectType.VIEW,)])
    def test_unknown_subject_does_not_resolve(self, subject_type: SubjectType) -> None:
        assert not resolve_subject(self.team.id, subject_type, uuid4()).exists

    def test_soft_deleted_subjects_do_not_resolve(self) -> None:
        table = self._table()
        table.deleted = True
        table.save()
        view = self._view()
        view.soft_delete()

        assert not resolve_subject(self.team.id, SubjectType.TABLE, table.id).exists
        assert not resolve_subject(self.team.id, SubjectType.VIEW, view.id).exists

    def test_another_teams_subject_does_not_resolve(self) -> None:
        table = self._table()
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        assert not resolve_subject(other_team.id, SubjectType.TABLE, table.id).exists


class TestReadableSubjectSnapshot(BaseTest):
    def _table(
        self, name: str, *, source: ExternalDataSource | None = None, url_pattern: str = "s3://bucket/x"
    ) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,
            columns={"id": {"clickhouse": "Int64", "hogql": "integer"}},
            external_data_source=source,
            url_pattern=url_pattern,
        )

    def _materialized_view(self, name: str = "orders") -> tuple[DataWarehouseSavedQuery, DataWarehouseTable]:
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        backing_table = self._table(
            f"{name}_backing", url_pattern=f"s3://bucket/{view.folder_path}/{view.normalized_name}"
        )
        view.table = backing_table
        view.is_materialized = True
        view.save(update_fields=["table", "is_materialized"])
        return view, backing_table

    def test_snapshot_exclusions_match_the_database_catalog(self) -> None:
        _view, backing_table = self._materialized_view()
        direct_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="direct_source",
            connection_id="direct_connection",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        direct_table = self._table("direct_customers", source=direct_source)
        plain_table = self._table("plain_customers")
        tables = (backing_table, direct_table, plain_table)

        database = Database.create_for(team=self.team, bypass_warehouse_access_control=True)
        catalog_excluded = {table.id for table in tables if not database.has_table(table.name)}
        readable = readable_subjects(self.team.id, set())
        snapshot_excluded = {table.id for table in tables} - readable.table_ids

        assert catalog_excluded == {backing_table.id, direct_table.id}
        assert snapshot_excluded == catalog_excluded

    def test_a_soft_deleted_views_backing_table_stays_out_of_the_snapshot(self) -> None:
        view, backing_table = self._materialized_view()
        view.deleted = True
        view.save(update_fields=["deleted"])

        readable = readable_subjects(self.team.id, set())

        assert backing_table.id not in readable.table_ids

    def test_backing_table_map_includes_soft_deleted_views_in_one_query(self) -> None:
        view, backing_table = self._materialized_view()
        view.deleted = True
        view.save(update_fields=["deleted"])
        source_table = self._table("source_orders")
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="source_orders_view",
            query={"kind": "HogQLQuery", "query": "SELECT * FROM source_orders"},
            table=source_table,
            is_materialized=True,
        )

        with self.assertNumQueries(1):
            backing_tables = data_modeling_facade.backing_table_ids_by_saved_query(self.team.id)

        assert backing_tables == {backing_table.id: view.id}
