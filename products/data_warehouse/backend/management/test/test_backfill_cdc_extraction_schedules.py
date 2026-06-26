import uuid
from datetime import timedelta
from io import StringIO

import pytest
from unittest.mock import patch

from django.core.management import call_command

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.django_db

BULK_HELPER_PATH = (
    "products.data_warehouse.backend.management.commands.backfill_cdc_extraction_schedules."
    "bulk_sync_cdc_extraction_schedules"
)


def _create_source(
    team,
    source_type: str = "Postgres",
    access_method: str = ExternalDataSource.AccessMethod.WAREHOUSE,
    deleted: bool = False,
) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        source_type=source_type,
        status="Completed",
        access_method=access_method,
        job_inputs={},
        deleted=deleted,
    )


def _create_schema(
    source,
    sync_type: str = ExternalDataSchema.SyncType.CDC,
    should_sync: bool = True,
    deleted: bool = False,
    interval: timedelta = timedelta(hours=6),
) -> ExternalDataSchema:
    schema = ExternalDataSchema.objects.create(
        name="TestSchema",
        team=source.team,
        source=source,
        should_sync=should_sync,
        sync_type=sync_type,
        sync_frequency_interval=interval,
        sync_time_of_day="00:00:00",
    )
    if deleted:
        schema.soft_delete()
    return schema


class TestBackfillCdcExtractionSchedules:
    def test_dry_run_does_not_call_helper(self, team):
        source = _create_source(team)
        _create_schema(source)

        with patch(BULK_HELPER_PATH) as mock_bulk:
            out = StringIO()
            call_command("backfill_cdc_extraction_schedules", stdout=out)

        assert mock_bulk.call_count == 0
        assert "Found 1 CDC sources to process (live_run=False)" in out.getvalue()
        assert "processed=1" in out.getvalue()

    def test_live_run_calls_bulk_helper_once(self, team):
        source = _create_source(team)
        _create_schema(source)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_cdc_extraction_schedules", "--live-run", stdout=out)

        assert mock_bulk.call_count == 1
        pairs = mock_bulk.call_args.args[0]
        assert len(pairs) == 1
        assert pairs[0][0].id == source.id
        assert "processed=1 failed=0" in out.getvalue()

    def test_interval_is_minimum_across_cdc_schemas(self, team):
        source = _create_source(team)
        _create_schema(source, interval=timedelta(hours=6))
        _create_schema(source, interval=timedelta(hours=1))

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            call_command("backfill_cdc_extraction_schedules", "--live-run")

        pairs = mock_bulk.call_args.args[0]
        # one source, deduped, with the minimum interval
        assert len(pairs) == 1
        assert pairs[0][1] == timedelta(hours=1)

    def test_skips_non_cdc_schemas(self, team):
        source = _create_source(team)
        _create_schema(source, sync_type=ExternalDataSchema.SyncType.FULL_REFRESH)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_cdc_extraction_schedules", "--live-run", stdout=out)

        assert mock_bulk.call_args.args[0] == []
        assert "Found 0 CDC sources" in out.getvalue()

    def test_skips_paused_and_deleted_cdc_schemas(self, team):
        source = _create_source(team)
        _create_schema(source, should_sync=False)
        _create_schema(source, deleted=True)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_cdc_extraction_schedules", "--live-run", stdout=out)

        assert mock_bulk.call_args.args[0] == []
        assert "Found 0 CDC sources" in out.getvalue()

    def test_skips_deleted_sources(self, team):
        # A soft-deleted source whose CDC schema was left non-deleted must not have its
        # schedule resurrected by the fleet-wide backfill.
        source = _create_source(team, deleted=True)
        _create_schema(source)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_cdc_extraction_schedules", "--live-run", stdout=out)

        assert mock_bulk.call_args.args[0] == []
        assert "Found 0 CDC sources" in out.getvalue()

    def test_skips_direct_query_sources(self, team):
        source = _create_source(team, access_method=ExternalDataSource.AccessMethod.DIRECT)
        _create_schema(source)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_cdc_extraction_schedules", "--live-run", stdout=out)

        assert mock_bulk.call_args.args[0] == []
        assert "Found 0 CDC sources" in out.getvalue()

    def test_team_id_filter(self, team):
        from posthog.models import Team

        other_team = Team.objects.create(organization=team.organization, name="other")
        source = _create_source(team)
        _create_schema(source)
        other_source = _create_source(other_team)
        _create_schema(other_source)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            call_command("backfill_cdc_extraction_schedules", "--live-run", "--team-id", str(team.id))

        pairs = mock_bulk.call_args.args[0]
        assert len(pairs) == 1
        assert pairs[0][0].team_id == team.id

    def test_source_type_filter(self, team):
        pg = _create_source(team, source_type="Postgres")
        _create_schema(pg)
        mysql = _create_source(team, source_type="MySQL")
        _create_schema(mysql)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            call_command("backfill_cdc_extraction_schedules", "--live-run", "--source-type", "Postgres")

        pairs = mock_bulk.call_args.args[0]
        assert len(pairs) == 1
        assert pairs[0][0].source_type == "Postgres"

    def test_reports_failures_from_bulk_helper(self, team):
        source = _create_source(team)
        _create_schema(source)

        with patch(BULK_HELPER_PATH, return_value=[(str(source.id), Exception("boom"))]) as mock_bulk:
            out = StringIO()
            call_command("backfill_cdc_extraction_schedules", "--live-run", stdout=out)

        assert mock_bulk.call_count == 1
        assert "processed=0" in out.getvalue()
        assert "failed=1" in out.getvalue()
