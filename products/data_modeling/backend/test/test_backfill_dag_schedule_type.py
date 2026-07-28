from unittest import mock

from parameterized import parameterized
from temporalio.client import ScheduleListActionStartWorkflow
from temporalio.common import SearchAttributePair, TypedSearchAttributes

from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_modeling.backend.management.commands.backfill_dag_schedule_type import _backfill_schedule_type
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW


class TestBackfillScheduleType:
    def _listing(self, schedule_id: str, workflow: str, schedule_type: str | None = None):
        action = mock.Mock(spec=ScheduleListActionStartWorkflow, workflow=workflow)
        attrs = TypedSearchAttributes(
            [SearchAttributePair(POSTHOG_SCHEDULE_TYPE_KEY, schedule_type)] if schedule_type else []
        )
        return mock.Mock(id=schedule_id, schedule=mock.Mock(action=action), typed_search_attributes=attrs)

    def _temporal(self, listings):
        async def fake_list_schedules(*args, **kwargs):
            async def gen():
                for listing in listings:
                    yield listing

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules
        temporal.get_schedule_handle = mock.Mock(return_value=mock.Mock(update=mock.AsyncMock()))
        return temporal

    @parameterized.expand(
        [
            ("dry_run", True, 0, []),
            ("real_run", False, 2, ["missing-1", "missing-2"]),
        ]
    )
    def test_counts_stamped_vs_missing_and_updates_only_missing(self, _name, dry_run, expected_updated, updated_ids):
        listings = [
            self._listing("already-stamped", DATA_MODELING_EXECUTE_DAG_WORKFLOW, DATA_MODELING_EXECUTE_DAG_WORKFLOW),
            self._listing("missing-1", DATA_MODELING_EXECUTE_DAG_WORKFLOW),
            self._listing("missing-2", DATA_MODELING_EXECUTE_DAG_WORKFLOW),
            self._listing("v1-schedule", "data-modeling-run"),
        ]
        temporal = self._temporal(listings)
        with mock.patch(
            "products.data_modeling.backend.management.commands.backfill_dag_schedule_type.async_connect",
            new=mock.AsyncMock(return_value=temporal),
        ):
            found, already_stamped, updated, failed = _backfill_schedule_type(dry_run)

        assert (found, already_stamped, updated, failed) == (3, 1, expected_updated, 0)
        assert [call.args[0] for call in temporal.get_schedule_handle.call_args_list] == updated_ids
