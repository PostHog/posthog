from asgiref.sync import async_to_sync

from products.data_modeling.backend.management.commands.delete_orphaned_saved_query_schedules import Command


class TestFindOrphansFromIds:
    def test_tier_schedule_ids_are_never_orphans(self):
        # "{dag_id}:{seconds}" is a live v2 cadence-tier schedule; treating it as an orphan
        # (the non-UUID fallback) would delete active DAG scheduling on operator input
        orphans = async_to_sync(Command()._find_orphans_from_ids)({"018f2a00-0000-0000-0000-000000000000:900"})
        assert orphans == set()
