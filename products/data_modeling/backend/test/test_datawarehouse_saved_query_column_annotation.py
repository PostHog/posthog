import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError

from posthog.models.scoping import team_scope

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.datawarehouse_saved_query_column_annotation import (
    DataWarehouseSavedQueryColumnAnnotation,
)


@pytest.mark.django_db
class TestDataWarehouseSavedQueryColumnAnnotation(BaseTest):
    def _saved_query(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

    def test_column_annotation_is_unique_per_saved_query_but_column_may_repeat_across_queries(self):
        first = self._saved_query("first_view")
        second = self._saved_query("second_view")

        with team_scope(self.team.id):
            DataWarehouseSavedQueryColumnAnnotation.objects.create(
                team=self.team,
                saved_query=first,
                column_name="revenue",
                description="Total revenue",
                description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.CANONICAL,
            )

            # Same column name on a different saved query is allowed — the constraint is composite.
            DataWarehouseSavedQueryColumnAnnotation.objects.create(
                team=self.team,
                saved_query=second,
                column_name="revenue",
                description="Total revenue",
                description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.CANONICAL,
            )

            # A duplicate (saved_query, column_name) is rejected.
            with pytest.raises(IntegrityError):
                DataWarehouseSavedQueryColumnAnnotation.objects.create(
                    team=self.team,
                    saved_query=first,
                    column_name="revenue",
                    description="Different description, same column",
                    description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.AI_GENERATED,
                )
