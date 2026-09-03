from uuid import uuid4

from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync

from products.data_modeling.backend.management.commands.delete_orphaned_dag_schedules import Command
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.test.helpers import temporal_listing


class TestDeleteOrphanedDagSchedules(BaseTest):
    def _orphans(self, schedule_ids) -> set[str]:
        return async_to_sync(Command()._find_orphans)(temporal_listing(schedule_ids), None)

    def test_only_schedules_whose_dag_is_gone_are_orphans(self):
        live = DAG.objects.create(team=self.team, name="live_dag")
        gone = uuid4()

        orphans = self._orphans([f"{live.id}:3600", str(live.id), f"{gone}:900", str(gone)])

        assert orphans == {f"{gone}:900", str(gone)}

    def test_a_schedule_id_without_a_dag_uuid_is_left_alone(self):
        orphans = self._orphans(["data-modeling-run-legacy-thing"])

        assert orphans == set()
