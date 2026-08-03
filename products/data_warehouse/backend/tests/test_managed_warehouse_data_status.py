from datetime import UTC, date, datetime

from freezegun import freeze_time

from django.test import SimpleTestCase

from products.data_warehouse.backend.logic.managed_warehouse_data_status import dataset_status
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)

Granularity = ManagedWarehouseBackfillPartition.Granularity
LifecycleState = ManagedWarehouseBackfillPartition.LifecycleState


@freeze_time("2026-07-13")
class TestDatasetStatus(SimpleTestCase):
    def _partition(
        self,
        *,
        partition_key: str,
        granularity: str,
        lifecycle_state: str = LifecycleState.COMPLETED,
        dataset: str = "events",
    ) -> ManagedWarehouseBackfillPartition:
        return ManagedWarehouseBackfillPartition(
            team_id=1,
            environment_id=1,
            dataset=dataset,
            partition_key=partition_key,
            granularity=granularity,
            lifecycle_state=lifecycle_state,
            run_id="run",
            started_at=datetime(2026, 7, 12, tzinfo=UTC),
            updated_at=datetime(2026, 7, 12, tzinfo=UTC),
        )

    def _backfill(self, earliest_event_date: date | None = date(2026, 3, 14)) -> ManagedWarehouseTeamMembership:
        return ManagedWarehouseTeamMembership(
            team_id=1,
            organization_id="org-a",
            schema_name="prod",
            enabled=True,
            backfill_enabled=True,
            table_names=ManagedWarehouseTableNames(
                events_table="events_prod",
                persons_table="persons_prod",
                data_imports_schema="posthog_data_imports_prod",
            ),
            earliest_event_date=earliest_event_date,
        )

    def test_daily_partitions_do_not_count_toward_historical_progress(self) -> None:
        # Daily runs land constantly once a team is live. Counting them as historical progress would
        # push completed past total and report a half-copied warehouse as up to date.
        partitions = [
            self._partition(partition_key="1_2026-03", granularity=Granularity.MONTH),
            self._partition(partition_key="1_2026-04", granularity=Granularity.MONTH),
            self._partition(partition_key="1_2026-07-11", granularity=Granularity.DAY),
            self._partition(partition_key="1_2026-07-12", granularity=Granularity.DAY),
        ]

        status = dataset_status(dataset="events", backfill=self._backfill(), partitions=partitions)

        # March through June is the historical range on 2026-07-13; only two months are done.
        assert status["completed_partitions"] == 2
        assert status["total_partitions"] == 4
        assert status["readiness_state"] == "backfilling"

    def test_events_are_up_to_date_once_every_historical_month_completes(self) -> None:
        partitions = [
            self._partition(partition_key=f"1_2026-0{month}", granularity=Granularity.MONTH) for month in (3, 4, 5, 6)
        ]

        status = dataset_status(dataset="events", backfill=self._backfill(), partitions=partitions)

        assert status["readiness_state"] == "up_to_date"
        assert status["completed_partitions"] == 4

    def test_persons_history_is_a_single_full_export(self) -> None:
        partitions = [self._partition(partition_key="1", granularity=Granularity.FULL, dataset="persons")]

        status = dataset_status(dataset="persons", backfill=self._backfill(), partitions=partitions)

        assert status["total_partitions"] == 1
        assert status["readiness_state"] == "up_to_date"

    def test_failed_partition_needs_attention_and_names_itself(self) -> None:
        partitions = [
            self._partition(partition_key="1_2026-03", granularity=Granularity.MONTH),
            self._partition(
                partition_key="1_2026-04", granularity=Granularity.MONTH, lifecycle_state=LifecycleState.FAILED
            ),
        ]

        status = dataset_status(dataset="events", backfill=self._backfill(), partitions=partitions)

        assert status["readiness_state"] == "needs_attention"
        assert status["current_partition"] == "1_2026-04"

    def test_unknown_history_range_is_still_waiting(self) -> None:
        # The scheduler caches earliest_event_date on first sight; until then there is no denominator.
        status = dataset_status(dataset="events", backfill=self._backfill(earliest_event_date=None), partitions=[])

        assert status["readiness_state"] == "waiting"
        assert status["total_partitions"] is None
