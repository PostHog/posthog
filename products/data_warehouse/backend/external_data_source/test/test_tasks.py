import uuid
import datetime as dt

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team
from posthog.redis import get_client

from products.data_warehouse.backend.tasks import (
    send_external_data_failure_digest_catchup,
    send_external_data_failure_digest_task,
    soft_delete_orphaned_external_data_schemas,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def _create_team_and_source(deleted: bool = False) -> tuple[Team, ExternalDataSource]:
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org, name="Test Team")
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        status="running",
        source_type="Stripe",
    )
    if deleted:
        ExternalDataSource.objects.filter(id=source.id).update(deleted=True)
    return team, source


class TestExternalDataFailureDigestTasks:
    def test_digest_task_builds_digest(self):
        with patch("products.data_warehouse.backend.tasks.notify_external_data_sync_failures") as mock_notify:
            send_external_data_failure_digest_task(123)

        mock_notify.assert_called_once_with(123)

    def test_digest_task_skips_when_another_send_is_in_flight(self):
        lock = get_client().lock("external_data_failure_digest:123", timeout=10)
        assert lock.acquire(blocking=False)
        try:
            with patch("products.data_warehouse.backend.tasks.notify_external_data_sync_failures") as mock_notify:
                send_external_data_failure_digest_task(123)
        finally:
            lock.release()

        mock_notify.assert_not_called()

    def test_catchup_fans_out_per_team(self):
        with (
            patch(
                "products.data_warehouse.backend.tasks.get_team_ids_with_recent_sync_failures",
                return_value=[1, 2],
            ),
            patch("products.data_warehouse.backend.tasks.send_external_data_failure_digest_task") as mock_task,
        ):
            send_external_data_failure_digest_catchup()

        assert [c.args for c in mock_task.delay.call_args_list] == [(1,), (2,)]


@pytest.mark.django_db
class TestSoftDeleteOrphanedExternalDataSchemas:
    @pytest.mark.parametrize("source_deleted,expected_deleted", [(True, True), (False, False)])
    def test_retires_only_schemas_of_deleted_sources(self, source_deleted, expected_deleted):
        team, source = _create_team_and_source(deleted=source_deleted)
        schema = ExternalDataSchema.objects.create(
            name="Charge", team=team, source=source, status=ExternalDataSchema.Status.FAILED
        )
        stale = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        ExternalDataSchema.objects.filter(id=schema.id).update(updated_at=stale)

        soft_delete_orphaned_external_data_schemas()

        schema.refresh_from_db()
        assert schema.deleted == expected_deleted
        assert (schema.deleted_at is not None) == expected_deleted
        assert (schema.updated_at is not None and schema.updated_at > stale) == expected_deleted

    def test_does_not_restamp_already_deleted_schema(self):
        team, source = _create_team_and_source(deleted=True)
        original = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            deleted=True,
            deleted_at=original,
        )

        soft_delete_orphaned_external_data_schemas()

        schema.refresh_from_db()
        assert schema.deleted_at == original
