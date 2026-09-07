from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from django.apps import apps

from products.customer_analytics.backend.logic.custom_property_sync import (
    _read_view,
    sync_custom_properties_for_account,
    sync_custom_property_values,
)
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
        assert self._active(self.globex, self.plan_def).value_str == "free"

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

    def test_skips_null_keys(self):
        self._source(self.mrr_def, "mrr")
        # selected columns are sorted: mrr, org_id — org_id (the key) is null, so the row can't match
        result = self._sync([(100.0, None)])

        assert result.written == 0
        assert result.unmatched_keys == 0

    def test_external_id_scope_only_syncs_that_account(self):
        self._source(self.mrr_def, "mrr")
        # selected columns are sorted: mrr, org_id
        with patch(_EXECUTE, return_value=_Response([(100.0, "acme")])):
            result = sync_custom_property_values(team_id=self.team.id, saved_query_id=self.view.id, external_id="acme")

        assert result.accounts_total == 1
        assert result.written == 1
        assert self._active(self.acme, self.mrr_def).value_num == 100.0
        assert not CustomPropertyValue.objects.filter(account=self.globex).exists()

    def test_external_id_scope_with_no_matching_account_writes_nothing(self):
        self._source(self.mrr_def, "mrr")
        with patch(_EXECUTE, return_value=_Response([])) as execute:
            result = sync_custom_property_values(
                team_id=self.team.id, saved_query_id=self.view.id, external_id="nobody"
            )

        assert result.accounts_total == 0
        assert result.written == 0
        execute.assert_not_called()  # empty key set -> zero batches -> no ClickHouse query

    def test_read_view_batches_key_filter_and_merges_rows(self):
        batch_size = "products.customer_analytics.backend.logic.custom_property_sync._SYNC_KEYS_PER_QUERY"
        responses = [_Response([(100.0, "acme")]), _Response([(200.0, "globex")])]
        with patch(_EXECUTE, side_effect=responses), patch(batch_size, 1):
            rows = _read_view(self.team, "billing_view", ["mrr", "org_id"], "org_id", ["acme", "globex"])

        assert rows == [(100.0, "acme"), (200.0, "globex")]


class SyncCustomPropertiesForAccountTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        DataWarehouseTable = apps.get_model("warehouse_sources", "DataWarehouseTable")
        self.table = DataWarehouseTable.objects.create(team=self.team, name="billing_view_mat", columns={})
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="billing_view", columns={"org_id": {}, "mrr": {}}, table=self.table
        )
        self.acme = Account.objects.create(team=self.team, name="Acme", external_id="acme")
        self.mrr_def = CustomPropertyDefinition.objects.create(
            team=self.team, name="MRR", display_type=DisplayType.NUMBER
        )
        self.source = CustomPropertySource.objects.create(
            team=self.team,
            definition=self.mrr_def,
            saved_query=self.view,
            source_column="mrr",
            key_column="org_id",
        )

    def test_writes_values_for_the_account(self):
        # selected columns are sorted: mrr, org_id
        with patch(_EXECUTE, return_value=_Response([(100.0, "acme")])):
            sync_custom_properties_for_account(team_id=self.team.id, external_id="acme")

        value = CustomPropertyValue.objects.get(account=self.acme, definition=self.mrr_def, is_deleted=False)
        assert value.value_num == 100.0

    def test_skips_unmaterialized_views(self):
        self.view.table = None
        self.view.save()
        with patch(_EXECUTE) as execute:
            sync_custom_properties_for_account(team_id=self.team.id, external_id="acme")

        execute.assert_not_called()

    def test_skips_disabled_sources(self):
        self.source.is_enabled = False
        self.source.save()
        with patch(_EXECUTE) as execute:
            sync_custom_properties_for_account(team_id=self.team.id, external_id="acme")

        execute.assert_not_called()

    def test_swallows_source_discovery_errors(self):
        discovery = "products.customer_analytics.backend.logic.custom_property_sync.CustomPropertySource"
        with patch(discovery) as source_model:
            source_model.objects.for_team.side_effect = Exception("db down")
            sync_custom_properties_for_account(team_id=self.team.id, external_id="acme")

    def test_swallows_errors_without_changing_source_health(self):
        with patch(_EXECUTE, side_effect=Exception("clickhouse down")):
            sync_custom_properties_for_account(team_id=self.team.id, external_id="acme")

        self.source.refresh_from_db()
        assert self.source.last_synced_at is None
        assert self.source.consecutive_failures == 0
        assert self.source.is_enabled is True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class ReadViewAccessControlTest(ClickhouseTestMixin, TeamScopedTestMixin, BaseTest):
    def test_userless_sync_reads_view_despite_warehouse_access_control(self):
        # The system sync runs with no user, so HogQL warehouse-view access control (flag on)
        # fails closed and denies the view unless the sync bypasses it.
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="account_health_scores",
            query={"kind": "HogQLQuery", "query": "SELECT 'acme' AS org_id, 100 AS health_score"},
            columns={"org_id": "String", "health_score": "Int64"},
        )

        rows = _read_view(self.team, view.name, ["health_score", "org_id"], "org_id", ["acme"])

        assert rows == [(100, "acme")]


class ReadViewLimitTest(ClickhouseTestMixin, TeamScopedTestMixin, BaseTest):
    def test_reads_all_matching_rows_beyond_default_hogql_limit(self):
        # An unfiltered, unlimited read gets capped at 100 rows by the HogQL default limit,
        # silently dropping most of a large view. 120 matches > 100 proves the cap is gone;
        # < 150 proves rows without a matching external_id are filtered out server-side.
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="org_scores",
            query={
                "kind": "HogQLQuery",
                "query": "SELECT toString(number) AS org_id, number AS score FROM numbers(150)",
            },
            columns={"org_id": "String", "score": "Int64"},
        )
        external_ids = [str(n) for n in range(120)]

        rows = _read_view(self.team, view.name, ["org_id", "score"], "org_id", external_ids)

        assert len(rows) == 120
