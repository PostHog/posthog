from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

from freezegun import freeze_time

from django.db.models import QuerySet
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_warehouse.backend.logic.managed_warehouse_data_status import (
    ReadinessState,
    SourceTableStatus,
    _rollup_sources,
    dataset_status,
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
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

Granularity = ManagedWarehouseBackfillPartition.Granularity
LifecycleState = ManagedWarehouseBackfillPartition.LifecycleState


class _AllowAllSourceAccess:
    def filter_queryset_by_access_level(self, queryset: QuerySet[ExternalDataSource]) -> QuerySet[ExternalDataSource]:
        return queryset


ALLOW_ALL_SOURCE_ACCESS = cast(UserAccessControl, _AllowAllSourceAccess())


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


def _table(
    *,
    source_name: str,
    table_name: str,
    readiness_state: ReadinessState,
    source_id: str | None = None,
    applied: bool = True,
    last_applied_at: datetime | None = None,
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
        "workflow_type": ManagedWarehouseSourceJobWorkflow.COPY,
        "workflow_status": ManagedWarehouseSourceJobStatus.COMPLETED,
        "workflow_started_at": datetime(2026, 8, 1, tzinfo=UTC),
        "applied": applied,
        "last_applied_at": last_applied_at,
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


def _record_source_workflow(
    *,
    team: Team,
    schema: ExternalDataSchema,
    status: ManagedWarehouseSourceJobStatus = ManagedWarehouseSourceJobStatus.COMPLETED,
    workflow_type: ManagedWarehouseSourceJobWorkflow = ManagedWarehouseSourceJobWorkflow.COPY,
    started_at: datetime | None = None,
    attempt_id: str | None = None,
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
