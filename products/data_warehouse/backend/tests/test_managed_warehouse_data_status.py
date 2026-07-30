from datetime import UTC, date, datetime
from uuid import uuid4

from freezegun import freeze_time

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.ducklake.models import DuckgresServerTeam, DuckgresSinkSchemaState
from posthog.models import Organization, Team

from products.data_warehouse.backend.logic.managed_warehouse_data_status import (
    QueueTailStatus,
    ReadinessState,
    SourceTableStatus,
    _rollup_sources,
    dataset_status,
    get_source_schema_statuses,
    sort_source_tables,
    source_table_readiness,
)
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

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


def _table(
    *,
    source_name: str,
    table_name: str,
    readiness_state: ReadinessState,
    source_id: str | None = None,
    backfilled: bool = True,
    pending_batches: int | None = None,
    last_synced_at: datetime | None = None,
) -> SourceTableStatus:
    return {
        "schema_id": str(uuid4()),
        "source_id": source_id or str(uuid4()),
        "source_name": source_name,
        "source_type": source_name,
        "table_name": table_name,
        "readiness_state": readiness_state,
        "detail": "",
        "backfilled": backfilled,
        "completed_chunks": 0,
        "total_chunks": None,
        "pending_batches": pending_batches,
        "oldest_pending_at": None,
        "last_applied_at": None,
        "last_synced_at": last_synced_at,
    }


class TestSortSourceTables(SimpleTestCase):
    def test_a_stalled_table_among_dozens_lands_on_the_first_page(self) -> None:
        # The table paginates at 20 rows. A team importing dozens of tables would otherwise have the
        # one that needs attention scattered anywhere by schema_id (a UUID), with no way to find it.
        tables = [
            _table(source_name="Stripe", table_name=f"table_{i}", readiness_state="up_to_date") for i in range(30)
        ]
        tables.insert(25, _table(source_name="Hubspot", table_name="contacts", readiness_state="needs_attention"))

        ordered = sort_source_tables(tables)

        assert ordered[0]["readiness_state"] == "needs_attention"
        assert ordered[0]["table_name"] == "contacts"

    def test_orders_by_severity_then_name(self) -> None:
        tables = [
            _table(source_name="Zendesk", table_name="tickets", readiness_state="up_to_date"),
            _table(source_name="Stripe", table_name="charges", readiness_state="catching_up"),
            _table(source_name="Hubspot", table_name="deals", readiness_state="needs_attention"),
            _table(source_name="Amplitude", table_name="events", readiness_state="catching_up"),
            _table(source_name="Salesforce", table_name="accounts", readiness_state="up_to_date"),
        ]

        ordered = [(table["source_name"], table["readiness_state"]) for table in sort_source_tables(tables)]

        assert ordered == [
            ("Hubspot", "needs_attention"),
            ("Amplitude", "catching_up"),
            ("Stripe", "catching_up"),
            ("Salesforce", "up_to_date"),
            ("Zendesk", "up_to_date"),
        ]


class TestRollupSources(SimpleTestCase):
    def test_counts_backfilled_schemas_independent_of_live_catch_up_state(self) -> None:
        # A schema can be fully backfilled but still "catching_up" on live imports. The rollup's
        # backfilled count must track the one-time historical copy, not the live readiness label,
        # or a source with a slow live queue would undercount how much history actually landed.
        stripe_id = str(uuid4())
        tables = [
            _table(
                source_id=stripe_id,
                source_name="Stripe",
                table_name="charges",
                readiness_state="up_to_date",
                backfilled=True,
            ),
            _table(
                source_id=stripe_id,
                source_name="Stripe",
                table_name="customers",
                readiness_state="catching_up",
                backfilled=True,
            ),
            _table(
                source_id=stripe_id,
                source_name="Stripe",
                table_name="invoices",
                readiness_state="waiting",
                backfilled=False,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["total_schemas"] == 3
        assert summary["backfilled_schemas"] == 2
        # catching_up outranks waiting in READINESS_PRIORITY, so it wins the rollup.
        assert summary["readiness_state"] == "catching_up"

    def test_groups_by_source_not_by_table(self) -> None:
        stripe_id, postgres_id = str(uuid4()), str(uuid4())
        tables = [
            _table(source_id=stripe_id, source_name="Stripe", table_name="charges", readiness_state="up_to_date"),
            _table(source_id=stripe_id, source_name="Stripe", table_name="customers", readiness_state="up_to_date"),
            _table(
                source_id=postgres_id, source_name="Postgres", table_name="orders", readiness_state="needs_attention"
            ),
        ]

        summaries = _rollup_sources(tables)

        assert {s["source_name"]: s["total_schemas"] for s in summaries} == {"Stripe": 2, "Postgres": 1}
        # needs_attention outranks up_to_date, so Postgres sorts first despite the alphabet.
        assert [s["source_name"] for s in summaries] == ["Postgres", "Stripe"]

    def test_pending_batches_null_propagates_rather_than_undercounting(self) -> None:
        # If the live queue check failed, reporting a partial sum (or zero) would read as "caught
        # up" when the real answer is "unknown" — null must survive the aggregation.
        source_id = str(uuid4())
        tables = [
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="charges",
                readiness_state="unknown",
                pending_batches=None,
            ),
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="customers",
                readiness_state="unknown",
                pending_batches=None,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["pending_batches"] is None

    def test_pending_batches_sums_across_schemas_when_queue_is_available(self) -> None:
        source_id = str(uuid4())
        tables = [
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="charges",
                readiness_state="catching_up",
                pending_batches=3,
            ),
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="customers",
                readiness_state="up_to_date",
                pending_batches=0,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["pending_batches"] == 3

    def test_last_synced_at_is_the_most_recent_across_schemas(self) -> None:
        source_id = str(uuid4())
        older = datetime(2026, 6, 1, tzinfo=UTC)
        newer = datetime(2026, 7, 1, tzinfo=UTC)
        tables = [
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="charges",
                readiness_state="up_to_date",
                last_synced_at=older,
            ),
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="customers",
                readiness_state="up_to_date",
                last_synced_at=newer,
            ),
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="invoices",
                readiness_state="waiting",
                last_synced_at=None,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["last_synced_at"] == newer

    def test_a_paused_schema_outranks_up_to_date_but_not_a_real_problem(self) -> None:
        # A source where some schemas aren't being kept current at all shouldn't read as fully
        # healthy, but an active problem elsewhere in the same source still has to win.
        source_id = str(uuid4())
        mostly_healthy = [
            _table(source_id=source_id, source_name="Stripe", table_name="charges", readiness_state="up_to_date"),
            _table(source_id=source_id, source_name="Stripe", table_name="invoices", readiness_state="sync_paused"),
        ]
        with_a_real_problem = [
            *mostly_healthy,
            _table(source_id=source_id, source_name="Stripe", table_name="refunds", readiness_state="needs_attention"),
        ]

        [healthy_summary] = _rollup_sources(mostly_healthy)
        [problem_summary] = _rollup_sources(with_a_real_problem)

        assert healthy_summary["readiness_state"] == "sync_paused"
        assert problem_summary["readiness_state"] == "needs_attention"

    def test_a_paused_schema_still_counts_toward_backfilled(self) -> None:
        # Pausing future syncs doesn't undo a historical backfill that already completed.
        source_id = str(uuid4())
        tables = [
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="charges",
                readiness_state="sync_paused",
                backfilled=True,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["backfilled_schemas"] == 1


class TestGetSourceSchemaStatuses(TestCase):
    # The queue-tail lookup reads SourceBatch, which lives in its own database.
    databases = {"default", "warehouse_sources_queue_db_writer"}

    def test_scopes_to_the_requested_source_only(self) -> None:
        # The modal fetches one source's schemas on click; a filter bug here would leak every
        # other connected source's tables into it.
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source_a = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        source_b = ExternalDataSource.objects.create(
            team=team, source_id="b", connection_id="cb", source_type="Postgres", status="Running"
        )
        schema_a = ExternalDataSchema.objects.create(team=team, name="charges", source=source_a)
        schema_b = ExternalDataSchema.objects.create(team=team, name="orders", source=source_b)
        DuckgresSinkSchemaState.objects.create(
            team=team, schema_id=schema_a.id, state=DuckgresSinkSchemaState.State.PRIMED
        )
        DuckgresSinkSchemaState.objects.create(
            team=team, schema_id=schema_b.id, state=DuckgresSinkSchemaState.State.PRIMED
        )

        result = get_source_schema_statuses(team.id, str(source_a.id))

        assert [row["schema_id"] for row in result] == [str(schema_a.id)]

    def test_a_paused_schema_is_visible_as_sync_paused_not_hidden(self) -> None:
        # A team that pauses a table's sync still has real data in the warehouse for it - it
        # should show up as paused, not vanish as if nothing were ever configured.
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        paused_schema = ExternalDataSchema.objects.create(team=team, name="charges", source=source, should_sync=False)
        DuckgresSinkSchemaState.objects.create(
            team=team, schema_id=paused_schema.id, state=DuckgresSinkSchemaState.State.PRIMED
        )

        [result] = get_source_schema_statuses(team.id, str(source.id))

        assert result["readiness_state"] == "sync_paused"
        assert result["backfilled"] is True

    def test_a_deleted_schema_stays_excluded_even_though_should_sync_no_longer_filters(self) -> None:
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        deleted_schema = ExternalDataSchema.objects.create(team=team, name="charges", source=source, deleted=True)
        DuckgresSinkSchemaState.objects.create(
            team=team, schema_id=deleted_schema.id, state=DuckgresSinkSchemaState.State.PRIMED
        )

        result = get_source_schema_statuses(team.id, str(source.id))

        assert result == []
