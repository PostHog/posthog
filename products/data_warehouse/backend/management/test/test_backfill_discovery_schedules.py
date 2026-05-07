import uuid
from io import StringIO

import pytest
from unittest.mock import patch

from django.core.management import call_command

from products.data_warehouse.backend.models import ExternalDataSource

pytestmark = pytest.mark.django_db


def _create_source(team, source_type: str = "Stripe", deleted: bool = False) -> ExternalDataSource:
    src = ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        source_type=source_type,
        status="Completed",
        job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test"}},
    )
    if deleted:
        src.soft_delete()
    return src


class TestBackfillDiscoverySchedules:
    def test_dry_run_does_not_call_helper(self, team):
        _create_source(team)
        _create_source(team)

        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule"
        ) as mock_sync:
            out = StringIO()
            call_command("backfill_discovery_schedules", stdout=out)

        assert mock_sync.call_count == 0
        assert "Found 2 sources to process (live_run=False)" in out.getvalue()
        assert "processed=2" in out.getvalue()

    def test_live_run_calls_helper_per_source(self, team):
        _create_source(team)
        _create_source(team)

        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule"
        ) as mock_sync:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert mock_sync.call_count == 2
        # Helper is called with create=False (idempotent upsert path)
        for call in mock_sync.call_args_list:
            assert call.kwargs == {"create": False}
        assert "processed=2 skipped_unregistered=0 failed=0" in out.getvalue()

    def test_skips_soft_deleted_sources(self, team):
        _create_source(team)
        _create_source(team, deleted=True)

        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule"
        ) as mock_sync:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert mock_sync.call_count == 1
        assert "Found 1 sources to process" in out.getvalue()

    def test_source_type_filter(self, team):
        _create_source(team, source_type="Stripe")
        _create_source(team, source_type="Hubspot")

        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule"
        ) as mock_sync:
            call_command("backfill_discovery_schedules", "--live-run", "--source-type", "Stripe")

        assert mock_sync.call_count == 1
        assert mock_sync.call_args.args[0].source_type == "Stripe"

    def test_team_id_filter(self, team):
        from posthog.models import Team

        other_team = Team.objects.create(organization=team.organization, name="other")
        _create_source(team)
        _create_source(other_team)

        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule"
        ) as mock_sync:
            call_command("backfill_discovery_schedules", "--live-run", "--team-id", str(team.id))

        assert mock_sync.call_count == 1
        assert mock_sync.call_args.args[0].team_id == team.id

    def test_skips_unregistered_source_types(self, team):
        _create_source(team, source_type="Stripe")
        _create_source(team, source_type="NotARealSourceType")

        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule"
        ) as mock_sync:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert mock_sync.call_count == 1
        assert "skipped_unregistered=1" in out.getvalue()

    def test_continues_after_per_source_failure(self, team):
        _create_source(team)
        _create_source(team)
        _create_source(team)

        # First call raises, the rest succeed — command must keep going and report failed=1.
        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule",
            side_effect=[Exception("boom"), None, None],
        ) as mock_sync:
            out = StringIO()
            call_command("backfill_discovery_schedules", "--live-run", stdout=out)

        assert mock_sync.call_count == 3
        assert "processed=2" in out.getvalue()
        assert "failed=1" in out.getvalue()

    def test_idempotent_when_helper_is_idempotent(self, team):
        _create_source(team)

        with patch(
            "products.data_warehouse.backend.management.commands.backfill_discovery_schedules.sync_discover_schemas_schedule"
        ) as mock_sync:
            call_command("backfill_discovery_schedules", "--live-run")
            call_command("backfill_discovery_schedules", "--live-run")

        # Helper called once per source per invocation; the helper itself is responsible for upsert semantics.
        assert mock_sync.call_count == 2
