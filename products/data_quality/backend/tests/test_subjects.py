from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import SubjectType
from products.data_quality.backend.logic.subjects import resolve_subject
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


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
