from datetime import UTC, date, datetime
from uuid import uuid4

from freezegun import freeze_time

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.ducklake.models import DuckgresServerTeam, DuckgresSinkSchemaState

from products.data_warehouse.backend.logic.managed_warehouse_data_status import (
    QueueTailStatus,
    ReadinessState,
    SourceTableStatus,
    dataset_status,
    sort_source_tables,
    source_table_readiness,
)
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition

Granularity = ManagedWarehouseBackfillPartition.Granularity
LifecycleState = ManagedWarehouseBackfillPartition.LifecycleState


class TestSourceTableReadiness(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "persistent_failure_overrides_pending_batches",
                DuckgresSinkSchemaState.State.BACKFILLING,
                3,
                {"pending_batches": 4, "oldest_pending_at": None, "last_applied_at": None},
                True,
                "needs_attention",
            ),
            (
                "primed_schema_with_pending_batches_is_catching_up",
                DuckgresSinkSchemaState.State.PRIMED,
                0,
                {"pending_batches": 2, "oldest_pending_at": None, "last_applied_at": None},
                True,
                "catching_up",
            ),
            (
                "primed_schema_without_pending_batches_is_up_to_date",
                DuckgresSinkSchemaState.State.PRIMED,
                0,
                {"pending_batches": 0, "oldest_pending_at": None, "last_applied_at": None},
                True,
                "up_to_date",
            ),
            (
                "queue_outage_does_not_report_up_to_date",
                DuckgresSinkSchemaState.State.PRIMED,
                0,
                None,
                False,
                "unknown",
            ),
        ]
    )
    def test_state_precedence(
        self,
        _name: str,
        lifecycle_state: str,
        consecutive_failures: int,
        queue_status: QueueTailStatus | None,
        queue_available: bool,
        expected_readiness: ReadinessState,
    ) -> None:
        state = DuckgresSinkSchemaState(
            team_id=1,
            schema_id=uuid4(),
            state=lifecycle_state,
            consecutive_failures=consecutive_failures,
        )

        readiness, _ = source_table_readiness(state, queue_status, queue_available)

        assert readiness == expected_readiness


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

    def _backfill(self, earliest_event_date: date | None = date(2026, 3, 14)) -> DuckgresServerTeam:
        return DuckgresServerTeam(team_id=1, backfill_enabled=True, earliest_event_date=earliest_event_date)

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


class TestSortSourceTables(SimpleTestCase):
    def _table(self, *, source_name: str, table_name: str, readiness_state: ReadinessState) -> SourceTableStatus:
        return {
            "schema_id": str(uuid4()),
            "source_id": str(uuid4()),
            "source_name": source_name,
            "source_type": source_name,
            "table_name": table_name,
            "readiness_state": readiness_state,
            "detail": "",
            "completed_chunks": 0,
            "total_chunks": None,
            "pending_batches": None,
            "oldest_pending_at": None,
            "last_applied_at": None,
            "last_synced_at": None,
        }

    def test_a_stalled_table_among_dozens_lands_on_the_first_page(self) -> None:
        # The table paginates at 20 rows. A team importing dozens of tables would otherwise have the
        # one that needs attention scattered anywhere by schema_id (a UUID), with no way to find it.
        tables = [
            self._table(source_name="Stripe", table_name=f"table_{i}", readiness_state="up_to_date") for i in range(30)
        ]
        tables.insert(25, self._table(source_name="Hubspot", table_name="contacts", readiness_state="needs_attention"))

        ordered = sort_source_tables(tables)

        assert ordered[0]["readiness_state"] == "needs_attention"
        assert ordered[0]["table_name"] == "contacts"

    def test_orders_by_severity_then_name(self) -> None:
        tables = [
            self._table(source_name="Zendesk", table_name="tickets", readiness_state="up_to_date"),
            self._table(source_name="Stripe", table_name="charges", readiness_state="catching_up"),
            self._table(source_name="Hubspot", table_name="deals", readiness_state="needs_attention"),
            self._table(source_name="Amplitude", table_name="events", readiness_state="catching_up"),
            self._table(source_name="Salesforce", table_name="accounts", readiness_state="up_to_date"),
        ]

        ordered = [(table["source_name"], table["readiness_state"]) for table in sort_source_tables(tables)]

        assert ordered == [
            ("Hubspot", "needs_attention"),
            ("Amplitude", "catching_up"),
            ("Stripe", "catching_up"),
            ("Salesforce", "up_to_date"),
            ("Zendesk", "up_to_date"),
        ]
