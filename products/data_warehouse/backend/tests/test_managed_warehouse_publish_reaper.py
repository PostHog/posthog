from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.ducklake.models import ManagedWarehousePublishedTable

from products.data_warehouse.backend.logic.managed_warehouse_publish_reaper import (
    STALE_AFTER,
    STALE_ERROR,
    mark_stale_publications_failed,
)


class TestManagedWarehousePublishReaper(APIBaseTest):
    def _publication(
        self,
        *,
        name: str,
        status: ManagedWarehousePublishedTable.Status,
        deleted: bool = False,
    ) -> ManagedWarehousePublishedTable:
        return ManagedWarehousePublishedTable.objects.for_team(self.team.pk).create(
            team=self.team,
            source_schema_name="main",
            source_table_name=name,
            name=name,
            status=status,
            deleted=deleted,
        )

    def test_marks_only_stale_active_publications_failed(self) -> None:
        pending = self._publication(name="pending", status=ManagedWarehousePublishedTable.Status.PENDING)
        publishing = self._publication(name="publishing", status=ManagedWarehousePublishedTable.Status.PUBLISHING)
        recent = self._publication(name="recent", status=ManagedWarehousePublishedTable.Status.PUBLISHING)
        completed = self._publication(name="completed", status=ManagedWarehousePublishedTable.Status.COMPLETED)
        deleted = self._publication(
            name="deleted",
            status=ManagedWarehousePublishedTable.Status.PUBLISHING,
            deleted=True,
        )
        stale_at = timezone.now() - STALE_AFTER - timedelta(minutes=1)
        ManagedWarehousePublishedTable.objects.unscoped().filter(
            id__in=[pending.id, publishing.id, completed.id, deleted.id]
        ).update(updated_at=stale_at)

        assert mark_stale_publications_failed() == 2

        for publication in [pending, publishing]:
            publication.refresh_from_db()
            assert publication.status == ManagedWarehousePublishedTable.Status.FAILED
            assert publication.last_error == STALE_ERROR
        for publication in [recent, completed, deleted]:
            previous_status = publication.status
            publication.refresh_from_db()
            assert publication.status == previous_status
