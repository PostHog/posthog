import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from django.apps import apps

from parameterized import parameterized

from products.customer_analytics.backend.logic.custom_property_sync import (
    MAX_CONSECUTIVE_SYNC_FAILURES,
    _read_view,
    record_sync_outcome,
    run_custom_property_sync,
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

    def test_run_sync_records_success_outcome(self):
        source = self._source(self.mrr_def, "mrr")
        with patch(_EXECUTE, return_value=_Response([(100.0, "acme")])):
            run_custom_property_sync(team_id=self.team.id, saved_query_id=self.view.id)

        source.refresh_from_db()
        assert source.last_synced_at is not None
        assert source.last_sync_error is None
        assert source.consecutive_failures == 0

    @patch("products.customer_analytics.backend.logic.custom_property_sync.capture_exception")
    def test_run_sync_records_failure_outcome_and_reraises(self, mock_capture):
        source = self._source(self.mrr_def, "mrr")
        sync_path = "products.customer_analytics.backend.logic.custom_property_sync.sync_custom_property_values"
        with patch(sync_path, side_effect=RuntimeError("boom")), pytest.raises(RuntimeError):
            run_custom_property_sync(team_id=self.team.id, saved_query_id=self.view.id)

        source.refresh_from_db()
        assert source.consecutive_failures == 1
        assert source.last_sync_error == "boom"
        mock_capture.assert_called_once()

    def test_read_view_batches_key_filter_and_merges_rows(self):
        batch_size = "products.customer_analytics.backend.logic.custom_property_sync._SYNC_KEYS_PER_QUERY"
        responses = [_Response([(100.0, "acme")]), _Response([(200.0, "globex")])]
        with patch(_EXECUTE, side_effect=responses), patch(batch_size, 1):
            rows = _read_view(self.team, "billing_view", ["mrr", "org_id"], "org_id", ["acme", "globex"])

        assert rows == [(100.0, "acme"), (200.0, "globex")]


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class ReadViewAccessControlTest(ClickhouseTestMixin, TeamScopedTestMixin, BaseTest):
    def test_userless_sync_reads_view_despite_warehouse_access_control(self):
        # The Celery sync runs with no user, so HogQL warehouse-view access control (flag on)
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


class RecordSyncOutcomeTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(team=self.team, name="billing_view", columns={})
        self.definition = CustomPropertyDefinition.objects.create(team=self.team, name="MRR")
        self.source = CustomPropertySource.objects.create(
            team=self.team, definition=self.definition, saved_query=self.view, source_column="mrr", key_column="org_id"
        )

    def _record(self, **kwargs):
        record_sync_outcome(team_id=self.team.id, saved_query_id=self.view.id, **kwargs)
        self.source.refresh_from_db()

    @parameterized.expand(
        [
            ("clean_success", {}, True, 0, None),
            ("view_not_found", {"view_found": False}, False, 0, "View not found"),
            ("run_failed", {"run_failed": True, "run_error": "boom"}, True, 1, "boom"),
        ]
    )
    def test_single_run_outcome(self, _name, kwargs, expected_enabled, expected_failures, expected_error):
        self._record(**kwargs)

        assert self.source.is_enabled is expected_enabled
        assert self.source.consecutive_failures == expected_failures
        assert self.source.last_sync_error == expected_error
        assert self.source.last_synced_at is not None

    def test_per_source_column_error_increments_only_that_source(self):
        other_def = CustomPropertyDefinition.objects.create(team=self.team, name="Plan")
        other = CustomPropertySource.objects.create(
            team=self.team, definition=other_def, saved_query=self.view, source_column="plan", key_column="org_id"
        )

        self._record(source_errors={str(self.source.id): "View billing_view has no column(s): mrr"})
        other.refresh_from_db()

        assert self.source.consecutive_failures == 1
        assert self.source.last_sync_error == "View billing_view has no column(s): mrr"
        assert other.consecutive_failures == 0
        assert other.last_sync_error is None

    def test_success_resets_failure_streak_and_clears_error(self):
        CustomPropertySource.objects.filter(id=self.source.id).update(consecutive_failures=3, last_sync_error="old")

        self._record()

        assert self.source.consecutive_failures == 0
        assert self.source.last_sync_error is None

    def test_view_not_found_disables_and_resets_failure_streak(self):
        CustomPropertySource.objects.filter(id=self.source.id).update(consecutive_failures=3)

        self._record(view_found=False)

        assert self.source.is_enabled is False
        assert self.source.consecutive_failures == 0

    @parameterized.expand(
        [("below_cap", MAX_CONSECUTIVE_SYNC_FAILURES - 2, True), ("at_cap", MAX_CONSECUTIVE_SYNC_FAILURES - 1, False)]
    )
    def test_auto_disables_at_failure_cap(self, _name, starting_failures, expected_enabled):
        CustomPropertySource.objects.filter(id=self.source.id).update(consecutive_failures=starting_failures)

        self._record(run_failed=True, run_error="boom")

        assert self.source.consecutive_failures == starting_failures + 1
        assert self.source.is_enabled is expected_enabled

    def test_disabled_sources_are_not_touched(self):
        CustomPropertySource.objects.filter(id=self.source.id).update(consecutive_failures=2, is_enabled=False)

        self._record()

        assert self.source.consecutive_failures == 2
        assert self.source.last_synced_at is None
