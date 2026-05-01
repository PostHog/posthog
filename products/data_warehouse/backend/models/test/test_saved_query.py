from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models.query import QuerySet as DjangoQuerySet

from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseSavedQuery, DataWarehouseTable
from products.data_warehouse.backend.models.modeling import DataWarehouseModelPath

DELETE_SAVED_QUERY_SCHEDULE = (
    "products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule"
)


class TestRevertMaterialization(BaseTest):
    """Tests for DataWarehouseSavedQuery.revert_materialization.

    The method runs three DB operations (table soft-delete, saved_query save,
    model paths delete) inside a transaction and then calls
    delete_saved_query_schedule — a Temporal RPC — OUTSIDE the transaction,
    gated on a flag that's only set after the DB writes. The Temporal call
    must only run when the full transaction committed; if ANY of the DB
    operations fail and the transaction rolls back, the schedule must be
    left intact so the next retry can converge on a consistent state.
    """

    def setUp(self):
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(
            access_key="test_key",
            access_secret="test_secret",
            team=self.team,
        )
        self.table = DataWarehouseTable.objects.create(
            name="stripe_charge",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/stripe_charge/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}},
        )
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            table=self.table,
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=1),
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )
        DataWarehouseModelPath.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            path=["posthog_events", self.saved_query.id.hex],
        )

    def _assert_state_unchanged(self) -> None:
        """A rollback must leave every piece of state (saved_query, table, model paths)
        exactly as it was before revert_materialization was called."""
        self.saved_query.refresh_from_db()
        self.assertTrue(self.saved_query.is_materialized)
        self.assertEqual(self.saved_query.sync_frequency_interval, timedelta(hours=1))
        self.assertEqual(self.saved_query.status, DataWarehouseSavedQuery.Status.COMPLETED)
        self.assertIsNotNone(self.saved_query.table_id)

        self.table.refresh_from_db()
        self.assertFalse(self.table.deleted)

        self.assertTrue(DataWarehouseModelPath.objects.filter(team=self.team, saved_query=self.saved_query).exists())

    @patch(DELETE_SAVED_QUERY_SCHEDULE)
    def test_delete_schedule_called_when_all_operations_succeed(self, mock_delete_schedule):
        """Happy path: every DB op inside the atomic block commits, and then
        delete_saved_query_schedule runs exactly once."""
        self.saved_query.revert_materialization()

        mock_delete_schedule.assert_called_once_with(self.saved_query)

        self.saved_query.refresh_from_db()
        self.assertFalse(self.saved_query.is_materialized)
        self.assertIsNone(self.saved_query.sync_frequency_interval)
        self.assertIsNone(self.saved_query.status)
        self.assertIsNone(self.saved_query.table_id)

        self.table.refresh_from_db()
        self.assertTrue(self.table.deleted)

        self.assertFalse(DataWarehouseModelPath.objects.filter(team=self.team, saved_query=self.saved_query).exists())

    @patch(DELETE_SAVED_QUERY_SCHEDULE)
    def test_delete_schedule_not_called_when_table_soft_delete_raises(self, mock_delete_schedule):
        """If table.soft_delete() raises inside the atomic block:
        - the transaction rolls back
        - delete_saved_query_schedule is NOT called."""
        with patch.object(
            DataWarehouseTable,
            "soft_delete",
            side_effect=RuntimeError("table soft_delete failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "table soft_delete failed"):
                self.saved_query.revert_materialization()

        mock_delete_schedule.assert_not_called()
        self._assert_state_unchanged()

    @patch(DELETE_SAVED_QUERY_SCHEDULE)
    def test_delete_schedule_called_once_when_saved_query_save_raises(self, mock_delete_schedule):
        """If self.save() raises inside the atomic block:
        - the transaction rolls back, including the table soft_delete that ran earlier in the block
        - delete_saved_query_schedule called."""
        with patch.object(
            DataWarehouseSavedQuery,
            "save",
            side_effect=RuntimeError("saved query save failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "saved query save failed"):
                self.saved_query.revert_materialization()

        mock_delete_schedule.assert_called_once()
        self._assert_state_unchanged()

    @patch(DELETE_SAVED_QUERY_SCHEDULE)
    def test_delete_schedule_called_once_when_model_path_delete_raises(self, mock_delete_schedule):
        """If DataWarehouseModelPath.objects.filter(...).delete() raises inside the atomic block:
        - the transaction rolls back — including the table soft_delete and the saved_query save that ran earlier
        in the block
        - delete_saved_query_schedule is called."""
        original_delete = DjangoQuerySet.delete

        def failing_delete(self_qs, *args, **kwargs):
            # Only raise for DataWarehouseModelPath querysets so that test fixture
            # cleanup and any unrelated delete calls still work normally.
            if self_qs.model is DataWarehouseModelPath:
                raise RuntimeError("model path delete failed")
            return original_delete(self_qs, *args, **kwargs)

        with patch.object(DjangoQuerySet, "delete", failing_delete):
            with self.assertRaisesRegex(RuntimeError, "model path delete failed"):
                self.saved_query.revert_materialization()

        mock_delete_schedule.assert_called_once()
        self._assert_state_unchanged()
