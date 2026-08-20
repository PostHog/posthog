from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from products.data_catalog.backend.facade.enums import MetricStatus
from products.data_catalog.backend.models import Metric


class TestMetricModel(BaseTest):
    def _create(self, name: str, **kwargs) -> Metric:
        return Metric.objects.for_team(self.team.id).create(team=self.team, name=name, description="desc", **kwargs)

    def test_name_is_unique_per_team(self) -> None:
        self._create("mrr")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create("mrr")

    def test_soft_deleted_name_is_reusable(self) -> None:
        # The unique constraint is partial on deleted=False: deleting frees the name, and any number
        # of tombstones may share it.
        first = self._create("mrr")
        Metric.objects.for_team(self.team.id).filter(pk=first.pk).update(deleted=True)
        second = self._create("mrr")
        assert second.id != first.id
        Metric.objects.for_team(self.team.id).filter(pk=second.pk).update(deleted=True)
        self._create("mrr")
        assert Metric.objects.for_team(self.team.id).filter(name="mrr").count() == 3

    def test_definition_kind_derived_from_definition(self) -> None:
        stub = self._create("stub")
        assert stub.definition_kind is None
        defined = self._create("defined", definition={"kind": "HogQLQuery", "query": "select 1"})
        assert defined.definition_kind == "HogQLQuery"

    def test_defaults(self) -> None:
        metric = self._create("mrr")
        assert metric.status == MetricStatus.PROPOSED
        assert metric.referenced_table_names == []
        assert metric.deleted is False
