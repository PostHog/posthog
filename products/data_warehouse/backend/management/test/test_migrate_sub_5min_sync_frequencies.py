from datetime import timedelta

import pytest
from unittest import mock

from django.core.management import call_command

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

pytestmark = [pytest.mark.django_db]

COMMAND = "products.data_warehouse.backend.management.commands.migrate_sub_5min_sync_frequencies"


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _create_schema(source, name, interval, sync_type=ExternalDataSchema.SyncType.CDC, deleted=False):
    return ExternalDataSchema.objects.create(
        name=name,
        team=source.team,
        source=source,
        should_sync=True,
        sync_type=sync_type,
        sync_frequency_interval=interval,
        deleted=deleted,
    )


def test_bumps_sub_floor_schemas_and_resyncs_schedules(team):
    cdc_source = ExternalDataSource.objects.create(team=team, source_type="Postgres", job_inputs={})
    other_source = ExternalDataSource.objects.create(team=team, source_type="Stripe", job_inputs={})
    deleted_source = ExternalDataSource.objects.create(team=team, source_type="Postgres", job_inputs={})

    cdc_fast_1 = _create_schema(cdc_source, "public.orders", timedelta(minutes=1))
    cdc_fast_2 = _create_schema(cdc_source, "public.users", timedelta(minutes=1))
    non_cdc_fast = _create_schema(
        other_source, "invoices", timedelta(minutes=1), sync_type=ExternalDataSchema.SyncType.FULL_REFRESH
    )
    at_floor = _create_schema(
        other_source, "charges", timedelta(minutes=5), sync_type=ExternalDataSchema.SyncType.INCREMENTAL
    )
    slow = _create_schema(
        other_source, "customers", timedelta(hours=6), sync_type=ExternalDataSchema.SyncType.INCREMENTAL
    )
    deleted_fast = _create_schema(deleted_source, "public.legacy", timedelta(minutes=1), deleted=True)

    with (
        mock.patch(f"{COMMAND}.bulk_update_external_data_job_schedules", return_value=([], [])) as mock_bulk,
        mock.patch(f"{COMMAND}.sync_cdc_extraction_schedule") as mock_extraction,
    ):
        call_command("migrate_sub_5min_sync_frequencies")

    for schema in (cdc_fast_1, cdc_fast_2, non_cdc_fast, deleted_fast):
        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(minutes=5)
    at_floor.refresh_from_db()
    assert at_floor.sync_frequency_interval == timedelta(minutes=5)
    slow.refresh_from_db()
    assert slow.sync_frequency_interval == timedelta(hours=6)

    # Only live sub-floor schemas get their sync schedule re-issued; the deleted one's schedule is gone.
    mock_bulk.assert_called_once()
    resynced_ids = {schema.id for schema in mock_bulk.call_args.args[0]}
    assert resynced_ids == {cdc_fast_1.id, cdc_fast_2.id, non_cdc_fast.id}

    # The CDC extraction schedule is re-derived once per affected live CDC source.
    assert [call.args[0].id for call in mock_extraction.call_args_list] == [cdc_source.id]


def test_failed_schedule_update_leaves_interval_retryable(team):
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres", job_inputs={})
    failing = _create_schema(source, "public.orders", timedelta(minutes=1))
    succeeding = _create_schema(source, "public.users", timedelta(minutes=1))

    # bulk_update reports `failing`'s schedule update as a failure; its database interval must stay
    # sub-floor so a rerun retries it, while `succeeding` is bumped to the floor.
    failure = (str(failing.id), RuntimeError("boom"))
    with (
        mock.patch(f"{COMMAND}.bulk_update_external_data_job_schedules", return_value=([], [failure])),
        mock.patch(f"{COMMAND}.sync_cdc_extraction_schedule"),
    ):
        call_command("migrate_sub_5min_sync_frequencies")

    failing.refresh_from_db()
    succeeding.refresh_from_db()
    assert failing.sync_frequency_interval == timedelta(minutes=1)
    assert succeeding.sync_frequency_interval == timedelta(minutes=5)


def test_dry_run_changes_nothing(team):
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres", job_inputs={})
    schema = _create_schema(source, "public.orders", timedelta(minutes=1))

    with (
        mock.patch(f"{COMMAND}.bulk_update_external_data_job_schedules") as mock_bulk,
        mock.patch(f"{COMMAND}.sync_cdc_extraction_schedule") as mock_extraction,
    ):
        call_command("migrate_sub_5min_sync_frequencies", "--dry-run")

    schema.refresh_from_db()
    assert schema.sync_frequency_interval == timedelta(minutes=1)
    mock_bulk.assert_not_called()
    mock_extraction.assert_not_called()
