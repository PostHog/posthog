from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.data_warehouse.backend.sync_status import get_warehouse_sync_warnings
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestWarehouseSyncWarnings(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        self.credential = DataWarehouseCredential.objects.create(
            team=self.team,
            access_key="key",
            access_secret="secret",
        )
        self.table = DataWarehouseTable.objects.create(
            name="stripe_charge",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=self.source,
            credential=self.credential,
            url_pattern="http://host.docker.internal:19000/test/*.parquet",
            columns={"id": "String"},
        )
        self.now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def _make_schema(
        self,
        *,
        status: str | None,
        last_synced_at: datetime | None = None,
        sync_frequency_interval: timedelta | None = timedelta(hours=6),
        latest_error: str | None = None,
        should_sync: bool = True,
    ) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=self.source,
            table=self.table,
            status=status,
            last_synced_at=last_synced_at,
            sync_frequency_interval=sync_frequency_interval,
            latest_error=latest_error,
            should_sync=should_sync,
        )

    def test_no_warnings_for_self_managed_table(self) -> None:
        self.table.external_data_source = None
        self.table.save()
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert warnings == []

    def test_no_warnings_when_completed(self) -> None:
        self._make_schema(
            status=ExternalDataSchema.Status.COMPLETED,
            last_synced_at=self.now - timedelta(hours=1),
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert warnings == []

    def test_no_warning_when_running_within_interval(self) -> None:
        self._make_schema(
            status=ExternalDataSchema.Status.RUNNING,
            last_synced_at=self.now - timedelta(hours=6),
            sync_frequency_interval=timedelta(hours=6),
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert warnings == []

    @parameterized.expand(
        [
            (ExternalDataSchema.Status.FAILED,),
            (ExternalDataSchema.Status.BILLING_LIMIT_REACHED,),
            (ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW,),
            (ExternalDataSchema.Status.PAUSED,),
        ]
    )
    def test_warning_for_problem_statuses(self, status: str) -> None:
        self._make_schema(
            status=status,
            last_synced_at=self.now - timedelta(hours=2),
            latest_error="boom" if status == ExternalDataSchema.Status.FAILED else None,
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.table_name == "stripe_charge"
        assert warning.schema_name == "Charge"
        assert warning.source_type == ExternalDataSourceType.STRIPE
        assert warning.status == str(status)
        assert "stripe_charge" in warning.message

    def test_failed_does_not_leak_raw_error(self) -> None:
        self._make_schema(
            status=ExternalDataSchema.Status.FAILED,
            last_synced_at=self.now - timedelta(hours=2),
            latest_error="connection to db-prod-1.internal:5432 failed: password authentication failed",
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert len(warnings) == 1
        # Raw error text (hostnames, credentials) must not reach the warning message.
        assert "db-prod-1.internal" not in warnings[0].message
        assert "password" not in warnings[0].message
        assert "data warehouse source" in warnings[0].message.lower()

    def test_warning_when_running_but_stale(self) -> None:
        self._make_schema(
            status=ExternalDataSchema.Status.RUNNING,
            sync_frequency_interval=timedelta(hours=6),
            last_synced_at=self.now - timedelta(hours=13),
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert len(warnings) == 1
        assert warnings[0].status == str(ExternalDataSchema.Status.RUNNING)
        assert "more than twice" in warnings[0].message

    def test_no_warning_when_running_at_exact_threshold(self) -> None:
        self._make_schema(
            status=ExternalDataSchema.Status.RUNNING,
            sync_frequency_interval=timedelta(hours=6),
            last_synced_at=self.now - timedelta(hours=12),
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert warnings == []

    def test_no_warning_when_running_without_interval(self) -> None:
        self._make_schema(
            status=ExternalDataSchema.Status.RUNNING,
            sync_frequency_interval=None,
            last_synced_at=self.now - timedelta(days=5),
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert warnings == []

    def test_should_not_sync_treated_as_paused(self) -> None:
        self._make_schema(
            status=ExternalDataSchema.Status.COMPLETED,
            should_sync=False,
            last_synced_at=self.now - timedelta(hours=1),
        )
        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert len(warnings) == 1
        assert "paused" in warnings[0].message.lower()
        # status must be consistent with the "paused" message, not the raw schema status (Completed).
        assert warnings[0].status == ExternalDataSchema.Status.PAUSED

    def test_uses_preloaded_schemas_when_available(self) -> None:
        """If `_active_external_data_schemas` is set on the table, it's used directly without a DB query."""
        fake_schema = MagicMock(spec=ExternalDataSchema)
        fake_schema.name = "PreloadedSchema"
        fake_schema.status = ExternalDataSchema.Status.FAILED
        fake_schema.last_synced_at = self.now - timedelta(hours=3)
        fake_schema.sync_frequency_interval = timedelta(hours=6)
        fake_schema.latest_error = "preloaded error"
        fake_schema.should_sync = True
        fake_schema.source_id = self.source.id
        fake_schema.source = self.source

        self.table.__dict__["_active_external_data_schemas"] = [fake_schema]

        warnings = get_warehouse_sync_warnings(self.table, now=self.now)
        assert len(warnings) == 1
        assert warnings[0].schema_name == "PreloadedSchema"
        assert warnings[0].status == ExternalDataSchema.Status.FAILED
