import uuid
from io import StringIO

import pytest
from unittest.mock import patch

from django.core.management import call_command

from products.warehouse_sources.backend.facade.models import ExternalDataSource

pytestmark = pytest.mark.django_db

BULK_HELPER_PATH = (
    "products.data_warehouse.backend.management.commands.backfill_discovery_schedules."
    "bulk_sync_discover_schemas_schedules"
)


def _create_source(
    team,
    source_type: str = "Stripe",
    deleted: bool = False,
    access_method: str = ExternalDataSource.AccessMethod.WAREHOUSE,
) -> ExternalDataSource:
    src = ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        source_type=source_type,
        status="Completed",
        access_method=access_method,
        job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test"}},
    )
    if deleted:
        src.soft_delete()
    return src


class TestBackfillDiscoverySchedules:
    def test_dry_run_does_not_call_helper(self, team):
        _create_source(team)
        _create_source(team)

        with patch(BULK_HELPER_PATH) as mock_bulk:
            out = StringIO()
            call_command("backfill_discovery_schedules", stdout=out)

        assert mock_bulk.call_count == 0
        assert "Found 2 sources to process (live_run=False)" in out.getvalue()
        assert "processed=2" in out.getvalue()

    def test_live_run_calls_bulk_helper_once(self, team):
        _create_source(team)
        _create_source(team)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        # Single bulk call over a shared connection, with both eligible sources.
        assert mock_bulk.call_count == 1
        assert len(mock_bulk.call_args.args[0]) == 2
        assert "processed=2 skipped_unregistered=0 failed=0" in out.getvalue()

    def test_skips_direct_query_sources(self, team):
        _create_source(team)
        _create_source(team, source_type="Postgres", access_method=ExternalDataSource.AccessMethod.DIRECT)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert len(mock_bulk.call_args.args[0]) == 1
        assert "Found 1 sources to process" in out.getvalue()

    def test_skips_soft_deleted_sources(self, team):
        _create_source(team)
        _create_source(team, deleted=True)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert len(mock_bulk.call_args.args[0]) == 1
        assert "Found 1 sources to process" in out.getvalue()

    def test_source_type_filter(self, team):
        _create_source(team, source_type="Stripe")
        _create_source(team, source_type="Hubspot")

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            call_command("backfill_discovery_schedules", "--live-run", "--source-type", "Stripe")

        eligible = mock_bulk.call_args.args[0]
        assert len(eligible) == 1
        assert eligible[0].source_type == "Stripe"

    def test_team_id_filter(self, team):
        from posthog.models import Team

        other_team = Team.objects.create(organization=team.organization, name="other")
        _create_source(team)
        _create_source(other_team)

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            call_command("backfill_discovery_schedules", "--live-run", "--team-id", str(team.id))

        eligible = mock_bulk.call_args.args[0]
        assert len(eligible) == 1
        assert eligible[0].team_id == team.id

    def test_skips_unregistered_source_types(self, team):
        _create_source(team, source_type="Stripe")
        _create_source(team, source_type="NotARealSourceType")

        with patch(BULK_HELPER_PATH, return_value=[]) as mock_bulk:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert len(mock_bulk.call_args.args[0]) == 1
        assert "skipped_unregistered=1" in out.getvalue()

    def test_reports_failures_from_bulk_helper(self, team):
        source = _create_source(team)
        _create_source(team)
        _create_source(team)

        # One source fails inside the bulk helper — command must report failed=1 and not raise.
        with patch(BULK_HELPER_PATH, return_value=[(str(source.id), Exception("boom"))]) as mock_bulk:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert mock_bulk.call_count == 1
        assert "processed=2" in out.getvalue()
        assert "failed=1" in out.getvalue()
