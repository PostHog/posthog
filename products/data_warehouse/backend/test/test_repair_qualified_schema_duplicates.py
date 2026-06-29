from datetime import UTC, datetime
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

# Patched at the defining module: update_should_sync imports these function-locally now.
_TEMPORAL = "products.data_warehouse.backend.logic.data_load.service"


class TestRepairQualifiedSchemaDuplicates(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
        )

    def _table(self, name: str) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=self.source,
            url_pattern="https://bucket/team_1/*",
            columns={"id": "String"},
        )

    def _schema(
        self, name: str, *, should_sync: bool, table: DataWarehouseTable | None, last_synced_at=None, source=None
    ):
        return ExternalDataSchema.objects.create(
            name=name,
            team=self.team,
            source=source or self.source,
            should_sync=should_sync,
            table=table,
            last_synced_at=last_synced_at,
        )

    def _run(self, *args: str) -> str:
        out = StringIO()
        # update_should_sync touches Temporal when re-enabling; stub those calls.
        with (
            patch(f"{_TEMPORAL}.external_data_workflow_exists", return_value=True),
            patch(f"{_TEMPORAL}.unpause_external_data_schedule") as unpause,
        ):
            call_command("repair_qualified_schema_duplicates", *args, stdout=out)
            self.unpause = unpause
        return out.getvalue()

    def test_dry_run_changes_nothing(self) -> None:
        live = self._schema("public.campaign_runs", should_sync=False, table=self._table("postgres_campaign_runs"))
        phantom = self._schema("campaign_runs", should_sync=False, table=None)

        self._run()  # dry-run default

        live.refresh_from_db()
        phantom.refresh_from_db()
        assert live.should_sync is False
        assert phantom.deleted is not True

    def test_live_run_reenables_live_and_soft_deletes_phantom(self) -> None:
        live = self._schema("public.campaign_runs", should_sync=False, table=self._table("postgres_campaign_runs"))
        phantom = self._schema("campaign_runs", should_sync=False, table=None)

        self._run("--live-run")

        live.refresh_from_db()
        phantom.refresh_from_db()
        assert live.should_sync is True
        assert phantom.deleted is True
        self.unpause.assert_called_once()

    def test_live_run_works_when_live_row_is_bare(self) -> None:
        # Symmetric case: the synced row is bare and the phantom is qualified.
        live = self._schema("campaign_runs", should_sync=False, table=self._table("postgres_campaign_runs"))
        phantom = self._schema("public.campaign_runs", should_sync=False, table=None)

        self._run("--live-run")

        live.refresh_from_db()
        phantom.refresh_from_db()
        assert live.should_sync is True
        assert phantom.deleted is True

    def test_multi_schema_two_live_rows_untouched(self) -> None:
        # Legit multi-schema: same table name in two schemas, both synced — must not be touched.
        a = self._schema("public.users", should_sync=True, table=self._table("postgres_public_users"))
        b = self._schema("analytics.users", should_sync=True, table=self._table("postgres_analytics_users"))

        out = self._run("--live-run")

        a.refresh_from_db()
        b.refresh_from_db()
        assert a.should_sync is True and a.deleted is not True
        assert b.should_sync is True and b.deleted is not True
        assert "skipped_ambiguous=1" in out

    def test_lone_disabled_row_not_reenabled(self) -> None:
        # No phantom twin → ambiguous (could be intentionally disabled) → leave it alone.
        lone = self._schema("public.campaign_runs", should_sync=False, table=self._table("postgres_campaign_runs"))

        self._run("--live-run")

        lone.refresh_from_db()
        assert lone.should_sync is False

    def test_phantom_that_has_synced_is_not_deleted(self) -> None:
        live = self._schema("public.campaign_runs", should_sync=False, table=self._table("postgres_campaign_runs"))
        # This twin has a last_synced_at, so it isn't a clean phantom — don't delete or re-enable blindly.
        not_phantom = self._schema(
            "campaign_runs", should_sync=False, table=None, last_synced_at=datetime(2026, 1, 1, tzinfo=UTC)
        )

        self._run("--live-run")

        live.refresh_from_db()
        not_phantom.refresh_from_db()
        assert live.should_sync is False
        assert not_phantom.deleted is not True

    def test_source_id_scoping(self) -> None:
        other_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="other",
            connection_id="other",
            source_type=ExternalDataSourceType.POSTGRES,
        )
        other_live = self._schema(
            "public.campaign_runs", should_sync=False, table=self._table("other_live"), source=other_source
        )
        self._schema("campaign_runs", should_sync=False, table=None, source=other_source)

        # Scope to self.source only — other_source must be left alone.
        self._run("--live-run", f"--source-id={self.source.id}")

        other_live.refresh_from_db()
        assert other_live.should_sync is False
