from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps

from products.customer_analytics.backend.logic.custom_property_sync import sync_custom_property_values
from products.customer_analytics.backend.models import (
    Account,
    CustomPropertyDefinition,
    CustomPropertySource,
    CustomPropertyValue,
)
from products.customer_analytics.backend.models.custom_property_definition import DisplayType
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin

DataWarehouseSavedQuery = apps.get_model("data_modeling", "DataWarehouseSavedQuery")

_EXECUTE = "products.customer_analytics.backend.logic.custom_property_sync.execute_hogql_query"


class _Response:
    def __init__(self, results):
        self.results = results


class CustomPropertySyncTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="billing_view", columns={"org_id": {}, "mrr": {}, "plan": {}}
        )
        self.acme = Account.objects.create(team=self.team, name="Acme", external_id="acme")
        self.globex = Account.objects.create(team=self.team, name="Globex", external_id="globex")
        self.mrr_def = CustomPropertyDefinition.objects.create(
            team=self.team, name="MRR", display_type=DisplayType.NUMBER
        )
        self.plan_def = CustomPropertyDefinition.objects.create(team=self.team, name="Plan")

    def _source(self, definition, source_column, key_column="org_id"):
        return CustomPropertySource.objects.create(
            team=self.team,
            definition=definition,
            saved_query=self.view,
            source_column=source_column,
            key_column=key_column,
        )

    def _sync(self, rows):
        with patch(_EXECUTE, return_value=_Response(rows)):
            return sync_custom_property_values(team_id=self.team.id, saved_query_id=self.view.id)

    def _active(self, account, definition):
        return CustomPropertyValue.objects.filter(account=account, definition=definition, is_deleted=False).get()

    def test_writes_matched_values_for_every_source(self):
        self._source(self.mrr_def, "mrr")
        self._source(self.plan_def, "plan")
        # selected columns are sorted: mrr, org_id, plan
        result = self._sync([(100.0, "acme", "enterprise"), (200.0, "globex", "free")])

        assert result.written == 4
        assert self._active(self.acme, self.mrr_def).value_num == 100.0
        assert self._active(self.globex, self.mrr_def).value_num == 200.0
        assert self._active(self.acme, self.plan_def).value_str == "enterprise"

    def test_skips_and_counts_unmatched_keys(self):
        self._source(self.mrr_def, "mrr")
        # selected columns are sorted: mrr, org_id
        result = self._sync([(100.0, "acme"), (999.0, "nobody")])

        assert result.written == 1
        assert result.unmatched_keys == 1
        assert not CustomPropertyValue.objects.filter(definition=self.mrr_def, account=self.globex).exists()

    def test_missing_column_marks_source_error_and_skips(self):
        source = self._source(self.mrr_def, "does_not_exist")
        result = self._sync([(100.0, "acme")])

        assert result.written == 0
        assert str(source.id) in result.source_errors

    def test_deleted_view_returns_not_found(self):
        self._source(self.mrr_def, "mrr")
        self.view.deleted = True
        self.view.save()

        result = self._sync([(100.0, "acme")])

        assert result.view_found is False
        assert result.written == 0

    def test_skips_null_values(self):
        self._source(self.mrr_def, "mrr")
        # selected columns are sorted: mrr, org_id
        result = self._sync([(None, "acme")])

        assert result.written == 0
        assert not CustomPropertyValue.objects.filter(definition=self.mrr_def, account=self.acme).exists()
