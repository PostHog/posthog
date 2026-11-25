from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import time_machine

from django.db.models import QuerySet
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_warehouse.backend.facade.contracts import LandingHistory, LandingHistoryBucket
from products.data_warehouse.backend.logic.managed_warehouse_data_status import (
    LandingState,
    ReadinessState,
    SourceTableStatus,
    _rollup_sources,
    dataset_status,
    get_managed_warehouse_landing_history,
    get_source_schema_statuses,
    sort_source_tables,
    source_table_readiness,
)
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceJobRecord,
    ManagedWarehouseSourceJobStatus,
    ManagedWarehouseSourceJobUpdate,
    ManagedWarehouseSourceJobWorkflow,
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.facade.testing import record_source_job_state
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource

Granularity = ManagedWarehouseBackfillPartition.Granularity
LifecycleState = ManagedWarehouseBackfillPartition.LifecycleState


class _AllowAllSourceAccess:
    def filter_queryset_by_access_level(self, queryset: QuerySet[ExternalDataSource]) -> QuerySet[ExternalDataSource]:
        return queryset


ALLOW_ALL_SOURCE_ACCESS = cast(UserAccessControl, _AllowAllSourceAccess())


class _DenySourcesAccess:
    def __init__(self, denied_source_ids: list) -> None:
        self.denied_source_ids = denied_source_ids

    def filter_queryset_by_access_level(self, queryset: QuerySet[ExternalDataSource]) -> QuerySet[ExternalDataSource]:
        return queryset.exclude(id__in=self.denied_source_ids)


class TestSourceTableReadiness(SimpleTestCase):
    @parameterized.expand(
        [
            ("failed_needs_attention", ManagedWarehouseSourceJobStatus.FAILED, "needs_attention"),
            ("running_is_backfilling", ManagedWarehouseSourceJobStatus.RUNNING, "backfilling"),
            ("completed_is_up_to_date", ManagedWarehouseSourceJobStatus.COMPLETED, "up_to_date"),
            ("skipped_is_waiting", ManagedWarehouseSourceJobStatus.SKIPPED, "waiting"),
            ("stale_is_waiting", ManagedWarehouseSourceJobStatus.STALE, "waiting"),
        ]
    )
    def test_state_precedence(
        self,
        _name: str,
        workflow_status: ManagedWarehouseSourceJobStatus,
        expected_readiness: ReadinessState,
    ) -> None:
        state = ManagedWarehouseSourceJobRecord(
            id=uuid4(),
            team_id=1,
            environment_id=1,
            schema_id=uuid4(),
            source_job_id="job-1",
            attempt_id="attempt-1",
            workflow_type=ManagedWarehouseSourceJobWorkflow.COPY,
            status=workflow_status,
            started_at=datetime(2026, 8, 1, tzinfo=UTC),
            finished_at=None,
            latest_error=None,
            workflow_id=None,
            workflow_run_id=None,
        )

        readiness, _ = source_table_readiness(state)

        assert readiness == expected_readiness

    def test_missing_workflow_is_waiting(self) -> None:
        readiness, _ = source_table_readiness(None)

        assert readiness == "waiting"


@time_machine.travel("2026-07-13", tick=False)
class TestDatasetStatus(SimpleTestCase):
    def _partition(
        self,
        *,
        partition_key: str,
        granularity: str,
        lifecycle_state: str = LifecycleState.COMPLETED,
        dataset: str = "events",
        period_start: date | None = None,
        completed_at: datetime | None = None,
        last_error: str | None = None,
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
            period_start=period_start,
            completed_at=completed_at,
            last_error=last_error,
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

    @parameterized.expand(
        [
            ("backfill_off", False, [], "not_in_warehouse"),
            ("nothing_has_run_yet", True, [], "not_in_warehouse"),
            ("failed_partition", True, [("1_2026-03", LifecycleState.FAILED)], "failing"),
            (
                "failed_beats_running",
                True,
                [("1_2026-03", LifecycleState.FAILED), ("1_2026-04", LifecycleState.RUNNING)],
                "failing",
            ),
            ("running_partition", True, [("1_2026-03", LifecycleState.RUNNING)], "behind"),
            ("history_incomplete", True, [("1_2026-03", LifecycleState.COMPLETED)], "behind"),
            (
                "history_complete",
                True,
                [(f"1_2026-0{month}", LifecycleState.COMPLETED) for month in (3, 4, 5, 6)],
                "in_sync",
            ),
        ]
    )
    def test_landing_state(
        self, _name: str, backfill_enabled: bool, specs: list[tuple[str, str]], expected: LandingState
    ) -> None:
        partitions = [
            self._partition(
                partition_key=key,
                granularity=Granularity.MONTH,
                lifecycle_state=lifecycle,
                completed_at=datetime(2026, 7, 12, tzinfo=UTC) if lifecycle == LifecycleState.COMPLETED else None,
            )
            for key, lifecycle in specs
        ]

        status = dataset_status(
            dataset="events", backfill=self._backfill() if backfill_enabled else None, partitions=partitions
        )

        assert status["landing_state"] == expected

    def test_failed_partition_exposes_its_error_and_count(self) -> None:
        partitions = [
            self._partition(
                partition_key="1_2026-04",
                granularity=Granularity.MONTH,
                lifecycle_state=LifecycleState.FAILED,
                last_error="copy timed out",
            ),
            self._partition(partition_key="1_2026-05", granularity=Granularity.MONTH),
        ]

        status = dataset_status(dataset="events", backfill=self._backfill(), partitions=partitions)

        assert status["failed_partitions"] == 1
        assert status["current_partition"] == "1_2026-04"
        assert status["last_error"] == "copy timed out"

    def test_last_completion_and_latest_day_come_from_completed_partitions_only(self) -> None:
        partitions = [
            self._partition(
                partition_key="1_2026-07-10",
                granularity=Granularity.DAY,
                period_start=date(2026, 7, 10),
                completed_at=datetime(2026, 7, 11, 1, tzinfo=UTC),
            ),
            self._partition(
                partition_key="1_2026-07-11",
                granularity=Granularity.DAY,
                period_start=date(2026, 7, 11),
                completed_at=datetime(2026, 7, 12, 1, tzinfo=UTC),
            ),
            self._partition(
                partition_key="1_2026-07-12",
                granularity=Granularity.DAY,
                period_start=date(2026, 7, 12),
                lifecycle_state=LifecycleState.RUNNING,
            ),
            self._partition(
                partition_key="1_2026-06",
                granularity=Granularity.MONTH,
                period_start=date(2026, 6, 1),
                completed_at=datetime(2026, 7, 13, 1, tzinfo=UTC),
            ),
        ]

        status = dataset_status(dataset="events", backfill=self._backfill(), partitions=partitions)

        assert status["latest_day_loaded"] == date(2026, 7, 11)
        assert status["last_completed_at"] == datetime(2026, 7, 13, 1, tzinfo=UTC)

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
    applied: bool = True,
    last_applied_at: datetime | None = None,
    last_synced_at: datetime | None = None,
    workflow_status: ManagedWarehouseSourceJobStatus = ManagedWarehouseSourceJobStatus.COMPLETED,
    landing_state: LandingState = "in_sync",
    pending_since: datetime | None = None,
    sync_status: str | None = "Completed",
) -> SourceTableStatus:
    return {
        "schema_id": str(uuid4()),
        "source_id": source_id or str(uuid4()),
        "source_name": source_name,
        "source_type": source_name,
        "table_name": table_name,
        "readiness_state": readiness_state,
        "detail": "",
        "workflow_type": ManagedWarehouseSourceJobWorkflow.COPY,
        "workflow_status": workflow_status,
        "workflow_started_at": datetime(2026, 8, 1, tzinfo=UTC),
        "applied": applied,
        "last_applied_at": last_applied_at,
        "last_synced_at": last_synced_at,
        "landing_state": landing_state,
        "pending_since": pending_since,
        "workflow_finished_at": None,
        "workflow_error": None,
        "sync_status": sync_status,
        "sync_error": None,
        "last_sync_rows": None,
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
            _table(source_name="Stripe", table_name="charges", readiness_state="backfilling"),
            _table(source_name="Hubspot", table_name="deals", readiness_state="needs_attention"),
            _table(source_name="Amplitude", table_name="events", readiness_state="backfilling"),
            _table(source_name="Salesforce", table_name="accounts", readiness_state="up_to_date"),
        ]

        ordered = [(table["source_name"], table["readiness_state"]) for table in sort_source_tables(tables)]

        assert ordered == [
            ("Hubspot", "needs_attention"),
            ("Amplitude", "backfilling"),
            ("Stripe", "backfilling"),
            ("Salesforce", "up_to_date"),
            ("Zendesk", "up_to_date"),
        ]


class TestRollupSources(SimpleTestCase):
    def test_counts_applied_schemas_independent_of_readiness_label(self) -> None:
        stripe_id = str(uuid4())
        tables = [
            _table(
                source_id=stripe_id,
                source_name="Stripe",
                table_name="charges",
                readiness_state="up_to_date",
                applied=True,
            ),
            _table(
                source_id=stripe_id,
                source_name="Stripe",
                table_name="customers",
                readiness_state="up_to_date",
                applied=True,
            ),
            _table(
                source_id=stripe_id,
                source_name="Stripe",
                table_name="invoices",
                readiness_state="waiting",
                applied=False,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["total_schemas"] == 3
        assert summary["applied_schemas"] == 2
        # waiting outranks up_to_date in READINESS_PRIORITY, so it wins the rollup.
        assert summary["readiness_state"] == "waiting"

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

    @parameterized.expand(
        [
            ("one_table", ["orders"], "The latest workflow failed for 1 table: orders. Select the source for details."),
            (
                "two_tables",
                ["refunds", "orders"],
                "The latest workflow failed for 2 tables: orders and refunds. Select the source for details.",
            ),
            (
                "exactly_as_many_as_fit",
                ["refunds", "orders", "charges"],
                "The latest workflow failed for 3 tables: charges, orders and refunds. Select the source for details.",
            ),
            (
                "more_than_fit",
                ["refunds", "orders", "Invoices", "charges", "payouts"],
                "The latest workflow failed for 5 tables: charges, Invoices, orders and 2 more. Select the source for details.",
            ),
            (
                "attention_without_a_failed_workflow",
                ["orders"],
                "One or more schemas need attention.",
                ManagedWarehouseSourceJobStatus.RUNNING,
            ),
        ]
    )
    def test_needs_attention_detail_names_the_failing_tables(
        self,
        _name: str,
        failing_tables: list[str],
        expected_detail: str,
        workflow_status: ManagedWarehouseSourceJobStatus = ManagedWarehouseSourceJobStatus.FAILED,
    ) -> None:
        source_id = str(uuid4())
        tables = [
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name=name,
                readiness_state="needs_attention",
                workflow_status=workflow_status,
            )
            for name in failing_tables
        ]
        tables.append(
            _table(source_id=source_id, source_name="Stripe", table_name="customers", readiness_state="up_to_date")
        )

        [summary] = _rollup_sources(tables)

        assert summary["detail"] == expected_detail

    def test_timestamps_roll_up_to_the_most_recent_across_schemas(self) -> None:
        # Both event timestamps summarize a source as "the latest time this happened anywhere in
        # it"; a min (or a None clobbering the max) would misreport an active source as stale.
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
                last_applied_at=newer,
            ),
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="customers",
                readiness_state="up_to_date",
                last_synced_at=newer,
                last_applied_at=older,
            ),
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="invoices",
                readiness_state="waiting",
                last_synced_at=None,
                last_applied_at=None,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["last_synced_at"] == newer
        assert summary["last_applied_at"] == newer

    def test_a_paused_schema_is_deprioritized_below_healthy_active_schemas(self) -> None:
        # Users often sync only a subset of a source, so an intentional pause should not mask the
        # health of schemas that are actively syncing. A source with only paused schemas stays paused.
        source_id = str(uuid4())
        paused = _table(
            source_id=source_id,
            source_name="Stripe",
            table_name="invoices",
            readiness_state="sync_paused",
        )
        mostly_healthy = [
            _table(source_id=source_id, source_name="Stripe", table_name="charges", readiness_state="up_to_date"),
            paused,
        ]
        with_a_real_problem = [
            *mostly_healthy,
            _table(source_id=source_id, source_name="Stripe", table_name="refunds", readiness_state="needs_attention"),
        ]

        [healthy_summary] = _rollup_sources(mostly_healthy)
        [paused_summary] = _rollup_sources([paused])
        [problem_summary] = _rollup_sources(with_a_real_problem)

        assert healthy_summary["readiness_state"] == "up_to_date"
        assert paused_summary["readiness_state"] == "sync_paused"
        assert problem_summary["readiness_state"] == "needs_attention"

    def test_a_paused_schema_still_counts_as_applied(self) -> None:
        source_id = str(uuid4())
        tables = [
            _table(
                source_id=source_id,
                source_name="Stripe",
                table_name="charges",
                readiness_state="sync_paused",
                applied=True,
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["applied_schemas"] == 1


class TestRollupLandingState(SimpleTestCase):
    @parameterized.expand(
        [
            ("failing_beats_everything", ["in_sync", "behind", "failing", "paused"], "failing"),
            ("behind_beats_not_in_warehouse", ["not_in_warehouse", "behind", "in_sync"], "behind"),
            ("not_in_warehouse_beats_in_sync", ["in_sync", "not_in_warehouse"], "not_in_warehouse"),
            ("in_sync_beats_paused", ["paused", "in_sync"], "in_sync"),
            ("all_paused", ["paused", "paused"], "paused"),
        ]
    )
    def test_source_landing_state_priority(self, _name: str, states: list[LandingState], expected: str) -> None:
        source_id = str(uuid4())
        tables = [
            _table(
                source_name="Stripe",
                table_name=f"t{index}",
                readiness_state="up_to_date",
                source_id=source_id,
                landing_state=state,
            )
            for index, state in enumerate(states)
        ]

        [summary] = _rollup_sources(tables)

        assert summary["landing_state"] == expected

    def test_counts_pending_since_and_failed_syncs_roll_up_per_source(self) -> None:
        source_id = str(uuid4())
        older = datetime(2026, 7, 10, tzinfo=UTC)
        newer = datetime(2026, 7, 12, tzinfo=UTC)
        tables = [
            _table(
                source_name="Stripe",
                table_name="a",
                readiness_state="backfilling",
                source_id=source_id,
                landing_state="behind",
                pending_since=newer,
            ),
            _table(
                source_name="Stripe",
                table_name="b",
                readiness_state="backfilling",
                source_id=source_id,
                landing_state="behind",
                pending_since=older,
            ),
            _table(
                source_name="Stripe",
                table_name="c",
                readiness_state="needs_attention",
                source_id=source_id,
                landing_state="failing",
                sync_status="Failed",
            ),
            _table(
                source_name="Stripe",
                table_name="d",
                readiness_state="sync_paused",
                source_id=source_id,
                landing_state="paused",
                sync_status="Failed",
            ),
        ]

        [summary] = _rollup_sources(tables)

        assert summary["landing_counts"] == {
            "in_sync": 0,
            "behind": 2,
            "failing": 1,
            "not_in_warehouse": 0,
            "paused": 1,
        }
        assert summary["pending_since"] == older
        assert summary["sync_failed_schemas"] == 1


def _record_source_workflow(
    *,
    team: Team,
    schema: ExternalDataSchema,
    status: ManagedWarehouseSourceJobStatus = ManagedWarehouseSourceJobStatus.COMPLETED,
    workflow_type: ManagedWarehouseSourceJobWorkflow = ManagedWarehouseSourceJobWorkflow.COPY,
    started_at: datetime | None = None,
    attempt_id: str | None = None,
    latest_error: str | None = None,
) -> datetime:
    started_at = started_at or datetime(2026, 7, 14, 11, 0, tzinfo=UTC)
    finished_at = started_at + timedelta(minutes=1)
    record_source_job_state(
        ManagedWarehouseSourceJobUpdate(
            team_id=team.id,
            schema_ids=[schema.id],
            source_job_id="external-job-1",
            attempt_id=attempt_id or f"{workflow_type.value}-attempt-1",
            workflow_type=workflow_type,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            latest_error=latest_error,
        )
    )
    return finished_at


class TestGetSourceSchemaStatuses(TestCase):
    def test_configured_schema_waits_before_a_workflow_runs(self) -> None:
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        schema = ExternalDataSchema.objects.create(team=team, name="charges", source=source)

        [result] = get_source_schema_statuses(team.id, str(source.id), user_access_control=ALLOW_ALL_SOURCE_ACCESS)

        assert result["schema_id"] == str(schema.id)
        assert result["readiness_state"] == "waiting"
        assert result["workflow_status"] is None

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
        _record_source_workflow(team=team, schema=schema_a)
        _record_source_workflow(team=team, schema=schema_b)

        result = get_source_schema_statuses(team.id, str(source_a.id), user_access_control=ALLOW_ALL_SOURCE_ACCESS)

        assert [row["schema_id"] for row in result] == [str(schema_a.id)]

    def test_a_paused_schema_is_visible_as_sync_paused_not_hidden(self) -> None:
        # A team that pauses a table's sync still has real data in the warehouse for it - it
        # should show up as paused, not vanish as if nothing were ever configured.
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        paused_schema = ExternalDataSchema.objects.create(team=team, name="charges", source=source, should_sync=False)
        _record_source_workflow(team=team, schema=paused_schema)

        [result] = get_source_schema_statuses(team.id, str(source.id), user_access_control=ALLOW_ALL_SOURCE_ACCESS)

        assert result["readiness_state"] == "sync_paused"
        assert result["applied"] is True

    def test_a_deleted_schema_stays_excluded_even_though_should_sync_no_longer_filters(self) -> None:
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        deleted_schema = ExternalDataSchema.objects.create(team=team, name="charges", source=source, deleted=True)
        _record_source_workflow(team=team, schema=deleted_schema)

        result = get_source_schema_statuses(team.id, str(source.id), user_access_control=ALLOW_ALL_SOURCE_ACCESS)

        assert result == []

    def test_reports_the_last_completed_workflow(self) -> None:
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        schema = ExternalDataSchema.objects.create(team=team, name="charges", source=source)
        applied_at = _record_source_workflow(
            team=team,
            schema=schema,
            workflow_type=ManagedWarehouseSourceJobWorkflow.REGISTER,
            started_at=datetime(2026, 7, 14, 11, 59, tzinfo=UTC),
        )

        [result] = get_source_schema_statuses(team.id, str(source.id), user_access_control=ALLOW_ALL_SOURCE_ACCESS)

        assert result["readiness_state"] == "up_to_date"
        assert result["last_applied_at"] == applied_at
        assert result["workflow_type"] == ManagedWarehouseSourceJobWorkflow.REGISTER

    def test_failed_latest_attempt_keeps_the_last_completed_application(self) -> None:
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )
        schema = ExternalDataSchema.objects.create(team=team, name="charges", source=source)
        applied_at = _record_source_workflow(team=team, schema=schema)
        _record_source_workflow(
            team=team,
            schema=schema,
            status=ManagedWarehouseSourceJobStatus.FAILED,
            workflow_type=ManagedWarehouseSourceJobWorkflow.REGISTER,
            started_at=applied_at + timedelta(minutes=1),
        )

        [result] = get_source_schema_statuses(team.id, str(source.id), user_access_control=ALLOW_ALL_SOURCE_ACCESS)

        assert result["readiness_state"] == "needs_attention"
        assert result["workflow_status"] == ManagedWarehouseSourceJobStatus.FAILED
        assert result["applied"] is True
        assert result["last_applied_at"] == applied_at


class TestSchemaLandingFacts(TestCase):
    def setUp(self) -> None:
        self.team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        self.source = ExternalDataSource.objects.create(
            team=self.team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )

    def _schema_status(self, schema: ExternalDataSchema) -> SourceTableStatus:
        [result] = get_source_schema_statuses(
            self.team.id, str(self.source.id), user_access_control=ALLOW_ALL_SOURCE_ACCESS
        )
        assert result["schema_id"] == str(schema.id)
        return result

    @parameterized.expand(
        [
            ("paused_beats_everything", False, ["completed", "failed"], 5, "paused", False),
            ("failed_latest_job", True, ["completed", "failed"], -5, "failing", False),
            ("never_applied", True, [], 5, "not_in_warehouse", True),
            ("only_a_running_job", True, ["running"], 5, "not_in_warehouse", True),
            ("running_after_an_applied_job", True, ["completed", "running"], -5, "behind", False),
            ("synced_after_last_apply", True, ["completed"], 5, "behind", True),
            ("synced_before_last_apply", True, ["completed"], -5, "in_sync", False),
        ]
    )
    def test_landing_state_precedence_and_pending_since(
        self,
        _name: str,
        should_sync: bool,
        attempts: list[str],
        synced_offset_minutes: int,
        expected_state: str,
        expects_pending: bool,
    ) -> None:
        schema = ExternalDataSchema.objects.create(
            team=self.team, name="charges", source=self.source, should_sync=should_sync
        )
        baseline = datetime(2026, 7, 14, 11, 0, tzinfo=UTC)
        for index, attempt in enumerate(attempts):
            _record_source_workflow(
                team=self.team,
                schema=schema,
                status=ManagedWarehouseSourceJobStatus(attempt),
                started_at=baseline + timedelta(hours=index),
                attempt_id=f"attempt-{index}",
            )
        last_applied = baseline + timedelta(minutes=1)
        synced_at = last_applied + timedelta(minutes=synced_offset_minutes)
        ExternalDataSchema.objects.filter(id=schema.id).update(last_synced_at=synced_at)

        result = self._schema_status(schema)

        assert result["landing_state"] == expected_state
        assert result["pending_since"] == (synced_at if expects_pending else None)

    def test_workflow_error_is_only_returned_for_a_failed_latest_job(self) -> None:
        failed_schema = ExternalDataSchema.objects.create(team=self.team, name="charges", source=self.source)
        _record_source_workflow(
            team=self.team,
            schema=failed_schema,
            status=ManagedWarehouseSourceJobStatus.FAILED,
            latest_error="register timed out",
        )

        failed = self._schema_status(failed_schema)

        assert failed["workflow_error"] == "register timed out"
        assert failed["workflow_finished_at"] == datetime(2026, 7, 14, 11, 1, tzinfo=UTC)

        failed_schema.delete()
        recovered_schema = ExternalDataSchema.objects.create(team=self.team, name="refunds", source=self.source)
        _record_source_workflow(
            team=self.team,
            schema=recovered_schema,
            status=ManagedWarehouseSourceJobStatus.RUNNING,
            latest_error="stale text from a retry",
        )

        assert self._schema_status(recovered_schema)["workflow_error"] is None

    def test_sync_facts_come_from_the_schema_and_its_latest_completed_job(self) -> None:
        schema = ExternalDataSchema.objects.create(
            team=self.team, name="charges", source=self.source, status="Failed", latest_error="auth rejected"
        )
        for status, rows, finished in [
            ("Completed", 10, datetime(2026, 7, 10, tzinfo=UTC)),
            ("Completed", 25, datetime(2026, 7, 12, tzinfo=UTC)),
            ("Failed", 99, datetime(2026, 7, 13, tzinfo=UTC)),
        ]:
            ExternalDataJob.objects.create(
                team=self.team,
                pipeline=self.source,
                schema=schema,
                status=status,
                rows_synced=rows,
                finished_at=finished,
            )

        result = self._schema_status(schema)

        assert result["sync_status"] == "Failed"
        assert result["sync_error"] == "auth rejected"
        assert result["last_sync_rows"] == 25

    def test_sync_error_is_hidden_while_the_upstream_sync_is_healthy(self) -> None:
        schema = ExternalDataSchema.objects.create(
            team=self.team, name="charges", source=self.source, status="Completed", latest_error="old failure"
        )

        result = self._schema_status(schema)

        assert result["sync_error"] is None
        assert result["last_sync_rows"] is None


@time_machine.travel("2026-07-14 03:00:00+00:00", tick=False)
class TestLandingHistory(TestCase):
    def setUp(self) -> None:
        self.team = Team.objects.create(
            organization=Organization.objects.create(name="org"), name="t", timezone="America/Los_Angeles"
        )
        self.source = ExternalDataSource.objects.create(
            team=self.team, source_id="a", connection_id="ca", source_type="Stripe", status="Running"
        )

    def _history(self, days: int = 7, access: object = ALLOW_ALL_SOURCE_ACCESS) -> LandingHistory:
        return get_managed_warehouse_landing_history(
            self.team.id,
            days=days,
            timezone_name=self.team.timezone,
            user_access_control=cast(UserAccessControl, access),
        )

    def _finish_attempt(
        self, schema: ExternalDataSchema, finished_at: datetime, status: ManagedWarehouseSourceJobStatus
    ) -> None:
        _record_source_workflow(
            team=self.team,
            schema=schema,
            status=status,
            started_at=finished_at - timedelta(minutes=1),
            attempt_id=f"attempt-{finished_at.isoformat()}-{status.value}",
        )

    def _partition(self, key: str, dataset: str, state: str, completed_at: datetime) -> None:
        ManagedWarehouseBackfillPartition.objects.for_team(self.team.id).create(
            team=self.team,
            environment_id=self.team.id,
            dataset=dataset,
            partition_key=key,
            granularity=Granularity.DAY,
            lifecycle_state=state,
            run_id="run",
            started_at=completed_at - timedelta(minutes=5),
            completed_at=completed_at,
        )

    def test_buckets_are_zero_filled_oldest_first_and_end_today_in_the_project_timezone(self) -> None:
        history = self._history(days=7)

        assert history.days == 7
        # 03:00 UTC on the 14th is still the evening of the 13th in Los Angeles.
        assert [bucket.date for bucket in history.buckets] == [date(2026, 7, day) for day in range(7, 14)]
        assert all(
            bucket.source_succeeded == bucket.source_failed == 0
            and bucket.backfill_succeeded == bucket.backfill_failed == 0
            for bucket in history.buckets
        )

    def test_counts_land_on_the_project_day_and_exclude_outside_the_window_and_groups(self) -> None:
        schema = ExternalDataSchema.objects.create(team=self.team, name="charges", source=self.source)
        late_evening_la = datetime(2026, 7, 14, 2, 0, tzinfo=UTC)
        self._finish_attempt(schema, late_evening_la, ManagedWarehouseSourceJobStatus.COMPLETED)
        self._finish_attempt(schema, late_evening_la + timedelta(minutes=5), ManagedWarehouseSourceJobStatus.FAILED)
        self._finish_attempt(
            schema, datetime(2026, 7, 10, 20, 0, tzinfo=UTC), ManagedWarehouseSourceJobStatus.COMPLETED
        )
        self._finish_attempt(schema, datetime(2026, 6, 1, tzinfo=UTC), ManagedWarehouseSourceJobStatus.COMPLETED)
        self._partition("1_2026-07-13", "events", LifecycleState.COMPLETED, late_evening_la)
        self._partition("1_2026-07-13", "persons", LifecycleState.FAILED, late_evening_la)
        self._partition("1_2026-07-13", "groups", LifecycleState.COMPLETED, late_evening_la)

        buckets = {bucket.date: bucket for bucket in self._history().buckets}

        assert buckets[date(2026, 7, 13)] == LandingHistoryBucket(
            date=date(2026, 7, 13), source_succeeded=1, source_failed=1, backfill_succeeded=1, backfill_failed=1
        )
        assert buckets[date(2026, 7, 10)].source_succeeded == 1
        assert sum(bucket.source_succeeded for bucket in buckets.values()) == 2

    def test_source_counts_exclude_deleted_and_unreadable_schemas(self) -> None:
        readable = ExternalDataSchema.objects.create(team=self.team, name="charges", source=self.source)
        deleted = ExternalDataSchema.objects.create(team=self.team, name="refunds", source=self.source, deleted=True)
        hidden_source = ExternalDataSource.objects.create(
            team=self.team, source_id="b", connection_id="cb", source_type="Postgres", status="Running"
        )
        hidden = ExternalDataSchema.objects.create(team=self.team, name="orders", source=hidden_source)
        finished = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
        for schema in (readable, deleted, hidden):
            self._finish_attempt(schema, finished, ManagedWarehouseSourceJobStatus.COMPLETED)

        history = self._history(access=_DenySourcesAccess([hidden_source.id]))

        assert sum(bucket.source_succeeded for bucket in history.buckets) == 1
