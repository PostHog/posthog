from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.db.utils import DatabaseError

import dagster
from parameterized import parameterized

from posthog.dags.eventproperty_cleanup import ops
from posthog.dags.eventproperty_cleanup.config import EventPropertyCleanupConfig
from posthog.dags.eventproperty_cleanup.cursor import (
    START,
    ResumePoint,
    cursor_asset_key,
    read_resume_point,
    record_resume_point,
)
from posthog.dags.eventproperty_cleanup.dormancy import (
    PROBE_UNAVAILABLE,
    DormancySignals,
    TenantEstimate,
    evaluate,
    still_dormant,
)
from posthog.dags.eventproperty_cleanup.engine import (
    MAX_RETRY_ATTEMPTS,
    DeleteEngine,
    DjangoPostgresBackend,
    HealthProbe,
    delete_statement,
)
from posthog.dags.eventproperty_cleanup.units import (
    WorkUnit,
    discover_pollution_units,
    discover_retention_units,
    iter_team_chunks,
)
from posthog.models import EventDefinition, EventProperty, Organization, PropertyDefinition, Team

NOW = datetime(2026, 8, 27, tzinfo=UTC)
# Fixtures whose age is compared against Postgres now() must be built from the real clock,
# otherwise they silently stop being "recent" once wall-clock time passes NOW + the window.
REAL_NOW = datetime.now(UTC)
HEALTHY = HealthProbe(dead_tuple_ratio=0.0, blocked_propdefs_backends=0)
UNHEALTHY = HealthProbe(dead_tuple_ratio=0.5, blocked_propdefs_backends=0)
POLLUTION_UNIT = WorkUnit(mode="pollution", team_id=1, project_id=1, key=("$pageview", "signup"), est_rows=5, reason="")


class FakePgError(Exception):
    def __init__(self, pgcode: str) -> None:
        super().__init__(pgcode)
        self.pgcode = pgcode


def database_error(pgcode: str) -> DatabaseError:
    error = DatabaseError("boom")
    error.__cause__ = FakePgError(pgcode)
    return error


class FakeBackend:
    def __init__(self, batches: list[int | Exception], probes: list[HealthProbe] | None = None) -> None:
        self.batches = list(batches)
        self.probes = list(probes or [HEALTHY])
        self.delete_calls: list[dict[str, Any]] = []
        self.vacuum_calls: list[tuple[int, int]] = []
        self.probe_calls = 0

    def delete_batch(self, statement: str, params: dict[str, Any], lock_timeout: str, statement_timeout: str) -> int:
        self.delete_calls.append(params)
        outcome = self.batches.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def probe_health(self) -> HealthProbe:
        self.probe_calls += 1
        return self.probes.pop(0) if len(self.probes) > 1 else self.probes[0]

    def vacuum(self, cost_delay_ms: int, cost_limit: int) -> list[str]:
        self.vacuum_calls.append((cost_delay_ms, cost_limit))
        return ["INFO: vacuuming"]


def make_engine(backend: FakeBackend, **config: Any) -> tuple[DeleteEngine, list[float]]:
    sleeps: list[float] = []
    cfg = EventPropertyCleanupConfig(dry_run=False, batch_size=100, sleep_seconds=0, **config)
    engine = DeleteEngine(cfg, backend, sleep=sleeps.append, clock=lambda: 0.0)
    return engine, sleeps


class TestDeleteEngine:
    def test_unit_ends_on_short_batch_and_counts_rows(self):
        backend = FakeBackend([100, 100, 7])
        engine, _ = make_engine(backend)

        result = engine.run_unit(POLLUTION_UNIT)

        assert (result.rows_deleted, result.batches, result.vacuums, result.stopped_reason) == (207, 3, 0, None)
        assert backend.vacuum_calls == []
        assert backend.delete_calls[0]["events"] == ["$pageview", "signup"]
        # No property list is bound: the worst project holds 1.38M non-event definitions, and the
        # re-check inside the statement already selects exactly the polluted rows.
        assert "properties" not in backend.delete_calls[0]

    def test_vacuums_once_when_row_budget_is_crossed(self):
        backend = FakeBackend([100, 100, 7])
        engine, _ = make_engine(backend, rows_between_vacuum=150, vacuum_cost_delay_ms=3, vacuum_cost_limit=50)

        result = engine.run_unit(POLLUTION_UNIT)

        assert backend.vacuum_calls == [(3, 50)]
        assert result.vacuums == 1
        assert result.rows_since_vacuum == 7
        assert engine.rows_since_vacuum == 7

    def test_vacuum_disabled_never_vacuums(self):
        backend = FakeBackend([100, 100, 7])
        engine, _ = make_engine(backend, rows_between_vacuum=150, vacuum=False)

        engine.run_unit(POLLUTION_UNIT)

        assert backend.vacuum_calls == []

    def test_max_rows_stops_the_unit(self):
        backend = FakeBackend([100, 100, 100])
        engine, _ = make_engine(backend, max_rows=150)

        result = engine.run_unit(POLLUTION_UNIT)

        assert result.stopped_reason == "max_rows"
        assert result.rows_deleted == 200
        assert len(backend.batches) == 1

    def test_pauses_while_unhealthy_then_resumes(self):
        backend = FakeBackend([100, 7], probes=[UNHEALTHY, UNHEALTHY, HEALTHY])
        engine, sleeps = make_engine(backend, pause_seconds=30, vacuum=False)

        result = engine.run_unit(POLLUTION_UNIT)

        assert result.pauses == 2
        assert sleeps.count(30) == 2
        assert result.rows_deleted == 107

    def test_dead_tuple_pressure_vacuums_instead_of_sleeping_forever(self):
        # Autovacuum only fires far above the pause threshold, and the job makes the dead tuples
        # itself, so sleeping here would hang the run. It must vacuum its way out.
        backend = FakeBackend([100, 7], probes=[UNHEALTHY, HEALTHY])
        engine, sleeps = make_engine(backend, pause_seconds=30, vacuum=True)

        result = engine.run_unit(POLLUTION_UNIT)

        assert backend.vacuum_calls != []
        assert 30 not in sleeps
        assert result.rows_deleted == 107

    def test_pause_gives_up_when_the_runtime_budget_is_spent(self):
        # An unbounded pause loop would ignore max_runtime_minutes and hold the pod forever.
        backend = FakeBackend([100] * 5, probes=[UNHEALTHY])
        cfg = EventPropertyCleanupConfig(
            dry_run=False, batch_size=100, sleep_seconds=0, vacuum=False, max_runtime_minutes=1
        )
        # The budget is spent the moment the first health probe reports pressure.
        engine = DeleteEngine(
            cfg, backend, sleep=lambda _: None, clock=lambda: 10_000.0 if backend.probe_calls else 0.0
        )

        result = engine.run_unit(POLLUTION_UNIT)

        assert result.stopped_reason == "max_runtime"
        assert result.rows_deleted == 0
        # Proves the budget was honoured inside the pause, not before it was ever entered.
        assert backend.probe_calls > 0

    def test_metrics_are_flushed_even_when_a_unit_fails(self):
        backend = FakeBackend([100, database_error("42P01")])
        metrics = MagicMock()
        cfg = EventPropertyCleanupConfig(dry_run=False, batch_size=100, sleep_seconds=0, metrics_flush_batches=1_000)
        engine = DeleteEngine(cfg, backend, metrics=metrics, metric_labels={"mode": "pollution"})

        with pytest.raises(DatabaseError):
            engine.run_unit(POLLUTION_UNIT)

        flushed = [c.args[0] for c in metrics.increment.call_args_list]
        assert "eventproperty_cleanup_rows_deleted" in flushed

    @parameterized.expand([("40001",), ("40P01",), ("55P03",), ("57014",)])
    def test_retryable_error_is_retried_with_a_pause(self, pgcode: str):
        backend = FakeBackend([database_error(pgcode), 7])
        engine, sleeps = make_engine(backend, pause_seconds=5)

        result = engine.run_unit(POLLUTION_UNIT)

        assert result.rows_deleted == 7
        assert result.pauses == 1
        assert 5 in sleeps

    def test_non_retryable_error_propagates(self):
        backend = FakeBackend([database_error("42P01")])
        engine, _ = make_engine(backend)

        with pytest.raises(DatabaseError):
            engine.run_unit(POLLUTION_UNIT)

    def test_retry_budget_is_finite(self):
        backend = FakeBackend([database_error("40001")] * (MAX_RETRY_ATTEMPTS + 1))
        engine, _ = make_engine(backend)

        with pytest.raises(DatabaseError):
            engine.run_unit(POLLUTION_UNIT)

    def test_failed_revalidation_stops_the_unit(self):
        backend = FakeBackend([100, 100, 100, 100, 7])
        engine, _ = make_engine(backend, revalidate_every_rows=200)
        answers = iter([True, False])

        result = engine.run_unit(POLLUTION_UNIT, revalidate=lambda: next(answers))

        assert result.stopped_reason == "revalidation_failed"
        assert result.batches == 4
        assert len(backend.batches) == 1

    def test_metrics_are_accumulated_and_flushed_in_bulk(self):
        backend = FakeBackend([100, 100, 100, 7])
        metrics = MagicMock()
        cfg = EventPropertyCleanupConfig(dry_run=False, batch_size=100, sleep_seconds=0, metrics_flush_batches=3)
        engine = DeleteEngine(cfg, backend, metrics=metrics, metric_labels={"mode": "pollution"})

        engine.run_unit(POLLUTION_UNIT)

        rows_calls = [c for c in metrics.increment.call_args_list if c.args[0] == "eventproperty_cleanup_rows_deleted"]
        assert [c.kwargs["value"] for c in rows_calls] == [300.0, 7.0]
        assert rows_calls[0].kwargs["labels"] == {"mode": "pollution"}


class TestTeamChunking:
    def test_walks_team_id_ranges_without_a_whole_table_statement(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (12,)
        cursor.fetchall.side_effect = [[(3,), (4,)], [], [(11,)]]
        config = EventPropertyCleanupConfig(discovery_team_chunk=5, discovery_sleep_seconds=0)

        chunks = list(iter_team_chunks(cursor, config, "UNIVERSE", {"days": 7}, sleep=lambda _: None))

        ranges = [c.kwargs or c.args[1] for c in cursor.execute.call_args_list[1:]]
        assert [(r["lo"], r["hi"]) for r in ranges] == [(0, 5), (5, 10), (10, 12)]
        assert all(r["days"] == 7 for r in ranges)
        assert chunks == [([3, 4], 5), ([], 10), ([11], 12)]

    def test_explicit_team_ids_skip_the_range_walk(self):
        cursor = MagicMock()
        config = EventPropertyCleanupConfig(team_ids=[9, 2])

        assert list(iter_team_chunks(cursor, config, "UNIVERSE", {})) == [([2, 9], 0)]
        cursor.execute.assert_not_called()

    def test_resumed_walk_skips_the_ranges_an_earlier_run_finished(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (12,)
        cursor.fetchall.side_effect = [[(11,)]]
        config = EventPropertyCleanupConfig(discovery_team_chunk=5, discovery_sleep_seconds=0)

        chunks = list(iter_team_chunks(cursor, config, "UNIVERSE", {}, sleep=lambda _: None, start_after=10))

        ranges = [c.kwargs or c.args[1] for c in cursor.execute.call_args_list[1:]]
        assert [(r["lo"], r["hi"]) for r in ranges] == [(10, 12)]
        assert chunks == [([11], 12)]


class TestResumePoint:
    def materialization(self, metadata: Any) -> Any:
        event = MagicMock()
        event.asset_materialization = dagster.AssetMaterialization(
            asset_key=cursor_asset_key("pollution"), metadata=metadata
        )
        return event

    def test_read_falls_back_to_the_start_when_the_instance_read_fails(self):
        # A Dagster+ read is a network call. It must never fail the run -- falling back to the start
        # is the behaviour the job had before the resume point existed.
        instance = MagicMock()
        instance.get_latest_materialization_event.side_effect = RuntimeError("cloud unavailable")

        assert read_resume_point(instance, "pollution") == START

    @parameterized.expand(
        [
            ("no_materialization", None, START),
            ("no_metadata", {}, START),
            ("unreadable_team", {"last_completed_team_id": "nope"}, START),
            ("team_only", {"last_completed_team_id": 25_000}, ResumePoint(last_completed_team_id=25_000)),
            ("negative_is_clamped", {"last_completed_team_id": -5}, START),
            (
                "mid_project",
                {
                    "last_completed_team_id": 5_000,
                    "in_progress_project_id": 5_101,
                    "in_progress_after_event": "$pageview",
                },
                ResumePoint(
                    last_completed_team_id=5_000,
                    in_progress_project_id=5_101,
                    in_progress_after_event="$pageview",
                ),
            ),
        ]
    )
    def test_read_tolerates_every_stored_shape(self, _name: str, metadata: Any, expected: ResumePoint):
        instance = MagicMock()
        instance.get_latest_materialization_event.return_value = (
            None if metadata is None else self.materialization(metadata)
        )

        assert read_resume_point(instance, "pollution") == expected

    @parameterized.expand(
        [
            ("the_cut_off_project", 5_101, "$pageview"),
            ("any_other_project", 7_777, ""),
            ("no_project_recorded", 0, ""),
        ]
    )
    def test_only_the_cut_off_project_resumes_mid_way(self, _name: str, project_id: int, expected: str):
        # Every other project has to start from its first event, or rows get skipped.
        point = ResumePoint(
            last_completed_team_id=5_000, in_progress_project_id=5_101, in_progress_after_event="$pageview"
        )

        assert point.event_start_for(project_id) == expected

    def test_each_mode_keeps_its_own_point(self):
        assert cursor_asset_key("pollution") != cursor_asset_key("retention")

    def test_record_never_raises(self):
        context = MagicMock()
        context.log_event.side_effect = RuntimeError("event log down")

        record_resume_point(context, "pollution", ResumePoint(last_completed_team_id=500))

        context.log.warning.assert_called_once()


class TestPollutionProgressRecords:
    def cursor_for(self, max_team_id: int, chunks: list[list[int]]) -> MagicMock:
        """A fake cursor serving one team per chunk, each project holding one page of events."""
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(max_team_id,)] + [(True,) for c in chunks for _ in c]
        fetchall: list[Any] = []
        for teams in chunks:
            fetchall.append([(t,) for t in teams])
            for t in teams:
                fetchall.append([(t, t, None)])
                fetchall.append([(f"evt_{t}",)])
                fetchall.append([])
        cursor.fetchall.side_effect = fetchall
        return cursor

    def test_a_mid_project_record_keeps_the_ranges_already_finished(self):
        # The mid-project record must carry the watermark this run reached, not the one it started
        # from. Carrying the starting value reverts it, so a resumed run re-walks finished ranges.
        cursor = self.cursor_for(10, [[3], [8]])
        config = EventPropertyCleanupConfig(discovery_team_chunk=5, discovery_sleep_seconds=0, pollution_event_batch=1)
        recorded: list[ResumePoint] = []

        for _unit in discover_pollution_units(cursor, config, sleep=lambda _: None, on_progress=recorded.append):
            pass

        # Project 8 sits in the second range, so its mid-project record must sit at 5, not 0.
        mid_for_8 = [p for p in recorded if p.in_progress_project_id == 8]
        assert mid_for_8
        assert all(p.last_completed_team_id == 5 for p in mid_for_8)
        assert [p.last_completed_team_id for p in recorded if not p.in_progress_project_id] == [5, 10]


class TestDeleteStatement:
    @parameterized.expand(
        [
            (
                "retention_without_its_window",
                WorkUnit(mode="retention", team_id=1, project_id=1, key=("a",), est_rows=0, reason=""),
            ),
        ]
    )
    def test_a_unit_missing_what_its_statement_binds_is_refused(self, _name: str, unit: WorkUnit):
        # These reach SQL as bound parameters; a missing one would surface as a driver error
        # mid-delete instead of failing the unit up front.
        with pytest.raises(ValueError):
            delete_statement(unit, 10, None)


def dormant_signals(**overrides: Any) -> DormancySignals:
    old = NOW - timedelta(days=400)
    base = DormancySignals(
        team_id=42,
        project_id=42,
        organization_id="org",
        est_rows=1000,
        event_defs=10,
        null_last_seen=0,
        max_last_seen=old,
        team_created_at=old,
        has_active_subscription=False,
        has_customer_id=False,
        is_pending_deletion=False,
        events_usage=0,
        last_login=old,
        last_personal_key_use=None,
        last_insight_view=old,
        last_activity_log=None,
        active_batch_exports=0,
        live_surveys=0,
        active_flags=0,
        persons_has_rows=False,
        persons_created_recently=False,
        clickhouse_recent_events=0,
    )
    return replace(base, **overrides)


class TestDormancyEvaluate:
    def test_all_signals_old_is_eligible(self):
        assert evaluate(dormant_signals(), 180, NOW).eligible

    @parameterized.expand(
        [
            ("recent_event", {"max_last_seen": NOW - timedelta(days=10)}, "event seen inside window"),
            ("null_last_seen", {"null_last_seen": 3}, "3 event definitions with NULL last_seen_at"),
            ("young_team", {"team_created_at": NOW - timedelta(days=30)}, "team younger than window"),
            ("subscription", {"has_active_subscription": True}, "organization has active subscription"),
            ("customer", {"has_customer_id": True}, "organization has billing customer"),
            ("usage", {"events_usage": 12}, "organization event usage not zero"),
            ("usage_unknown", {"events_usage": None}, "organization event usage not zero"),
            ("login", {"last_login": NOW - timedelta(days=1)}, "member logged in inside window"),
            ("api_key", {"last_personal_key_use": NOW}, "personal API key used inside window"),
            ("insight", {"last_insight_view": NOW}, "insight viewed inside window"),
            ("activity", {"last_activity_log": NOW}, "activity log inside window"),
            ("exports", {"active_batch_exports": 1}, "active batch exports"),
            ("surveys", {"live_surveys": 1}, "live surveys"),
            ("flags", {"active_flags": 2}, "active feature flags"),
            ("persons_recent", {"persons_created_recently": True}, "persons created inside window"),
            ("persons_unknown", {"persons_created_recently": None}, "persons probe unavailable"),
            ("clickhouse_events", {"clickhouse_recent_events": 5}, "events ingested inside window"),
            ("clickhouse_unknown", {"clickhouse_recent_events": None}, "clickhouse probe unavailable"),
            ("no_team", {"team_created_at": None}, "team not found"),
        ]
    )
    def test_single_signal_blocks_eligibility(self, _name: str, overrides: dict[str, Any], failure: str):
        verdict = evaluate(dormant_signals(**overrides), 180, NOW)

        assert not verdict.eligible
        assert failure in verdict.failures


class TestScoreDormantTeams:
    def test_units_only_for_eligible_and_approved_teams(self):
        eligible_a = dormant_signals(team_id=1)
        eligible_b = dormant_signals(team_id=2)
        active = dormant_signals(team_id=3, clickhouse_recent_events=100)
        config = EventPropertyCleanupConfig(
            dormant_discovery_enabled=True, dormant_approved_team_ids=[1, 3], never_delete_team_ids=[4]
        )
        by_team = {1: eligible_a, 2: eligible_b, 3: active}

        with (
            patch.object(
                ops,
                "top_teams",
                return_value=[TenantEstimate(team_id=t, est_rows=t * 10) for t in (1, 2, 3, 4)],
            ),
            patch.object(ops, "score_team", side_effect=lambda cursor, team_id, *a, **k: by_team[team_id]),
        ):
            verdicts, units = ops.score_dormant_teams(
                MagicMock(), config, lambda *_: PROBE_UNAVAILABLE, lambda *_: 0, NOW
            )

        assert [v.signals.team_id for v in verdicts] == [1, 2, 3]
        assert [(u.team_id, u.mode) for u in units] == [(1, "dormant")]


@pytest.mark.django_db
class TestPredicatesAgainstPostgres:
    def setup_method(self):
        org = Organization.objects.create(name="eventproperty-cleanup")
        self.team = Team.objects.create(organization=org, name="eventproperty-cleanup")
        self.project_id = self.team.project_id
        self.config = EventPropertyCleanupConfig(
            dry_run=False, team_ids=[self.team.id], skip_paying_orgs=False, batch_size=10, retention_days=180
        )

    def add_propdef(self, name: str, type_: int) -> PropertyDefinition:
        return PropertyDefinition.objects.create(team=self.team, project_id=self.project_id, name=name, type=type_)

    def add_row(self, event: str, prop: str) -> None:
        EventProperty.objects.create(team=self.team, project_id=self.project_id, event=event, property=prop)

    def rows(self) -> set[str]:
        return {
            f"{event}:{prop}"
            for event, prop in EventProperty.objects.filter(team=self.team).values_list("event", "property")
        }

    def run_units(self, units: list[WorkUnit]) -> int:
        backend = DjangoPostgresBackend()
        engine = DeleteEngine(self.config, backend, sleep=lambda _: None)
        return sum(engine.run_unit(u).rows_deleted for u in units)

    def discover_pollution(self, config: Any = None) -> list[WorkUnit]:
        with connection.cursor() as cursor:
            return list(discover_pollution_units(cursor, config or self.config))

    def test_pollution_deletes_person_only_properties_and_keeps_event_properties(self):
        self.add_propdef("$initial_geoip_city_name", PropertyDefinition.Type.PERSON)
        self.add_propdef("$browser", PropertyDefinition.Type.EVENT)
        self.add_propdef("$browser", PropertyDefinition.Type.PERSON)
        self.add_row("$pageview", "$initial_geoip_city_name")
        self.add_row("signup", "$initial_geoip_city_name")
        self.add_row("$pageview", "$browser")

        units = self.discover_pollution()

        assert sorted(units[0].key) == ["$pageview", "signup"]
        assert self.run_units(units) == 2
        assert self.rows() == {"$pageview:$browser"}

    def test_pollution_finds_rows_whose_event_has_no_definition(self):
        # Discovery reads events from posthog_eventproperty, not posthog_eventdefinition. On prod
        # 0.1% of rows have no definition row, and driving discovery from there would leave them
        # unreachable for good.
        self.add_propdef("$initial_os", PropertyDefinition.Type.PERSON)
        self.add_row("event_with_no_definition", "$initial_os")
        assert not EventDefinition.objects.filter(team=self.team).exists()

        units = self.discover_pollution()

        assert [tuple(u.key) for u in units] == [("event_with_no_definition",)]
        assert self.run_units(units) == 1
        assert self.rows() == set()

    def test_pollution_skips_a_project_with_nothing_polluted(self):
        # The gate is one EXISTS row. Without it every project's events get walked for nothing.
        self.add_propdef("$browser", PropertyDefinition.Type.EVENT)
        self.add_propdef("$browser", PropertyDefinition.Type.PERSON)
        self.add_row("$pageview", "$browser")

        assert self.discover_pollution() == []
        assert self.rows() == {"$pageview:$browser"}

    def test_pollution_never_binds_a_property_list(self):
        # A project can own over a million non-event definitions, so nothing may bind them all.
        for i in range(30):
            self.add_propdef(f"prop_{i:03d}", PropertyDefinition.Type.PERSON)
            self.add_row("$pageview", f"prop_{i:03d}")

        units = self.discover_pollution()

        statement, params = delete_statement(units[0], 10, None)
        assert "properties" not in params
        assert set(params) == {"project_id", "events", "batch"}
        assert self.run_units(units) == 30

    def test_an_explicit_team_ids_run_records_nothing(self):
        # Its ranges are meaningless, so recording one would reset the campaign's resume point.
        self.add_propdef("$initial_os", PropertyDefinition.Type.PERSON)
        self.add_row("$pageview", "$initial_os")
        recorded: list[ResumePoint] = []

        with connection.cursor() as cursor:
            for _unit in discover_pollution_units(cursor, self.config, on_progress=recorded.append):
                pass

        assert self.config.team_ids is not None
        assert recorded == []

    def test_pollution_events_are_paged_and_every_page_is_covered(self):
        # A project can hold more events than one page, and prod's largest holds so many that
        # counting them does not finish. Every page has to be walked.
        self.add_propdef("$initial_os", PropertyDefinition.Type.PERSON)
        for event in ("a_evt", "b_evt", "c_evt", "d_evt", "e_evt"):
            self.add_row(event, "$initial_os")
        config = replace_config(self.config, pollution_event_batch=2)

        units = self.discover_pollution(config)

        assert [tuple(u.key) for u in units] == [("a_evt", "b_evt"), ("c_evt", "d_evt"), ("e_evt",)]
        assert self.run_units(units) == 5
        assert self.rows() == set()

    def test_pollution_delete_never_selects_a_property_that_gained_an_event_definition(self):
        # The re-check lives inside the ctid subquery, so a property that became legitimate is not
        # selected at all. That keeps a short batch meaning "exhausted", which is what lets the run
        # record a resume point.
        self.add_propdef("plan", PropertyDefinition.Type.PERSON)
        self.add_propdef("keep", PropertyDefinition.Type.PERSON)
        self.add_row("upgrade", "plan")
        self.add_row("upgrade", "keep")
        units = self.discover_pollution()
        assert len(units) == 1

        self.add_propdef("plan", PropertyDefinition.Type.EVENT)

        assert self.run_units(units) == 1
        assert self.rows() == {"upgrade:plan"}

    def test_retention_deletes_stale_events_only(self):
        stale, fresh, unknown = "old_event", "new_event", "unknown_event"
        EventDefinition.objects.create(
            team=self.team, project_id=self.project_id, name=stale, last_seen_at=REAL_NOW - timedelta(days=400)
        )
        EventDefinition.objects.create(team=self.team, project_id=self.project_id, name=fresh, last_seen_at=REAL_NOW)
        EventDefinition.objects.create(team=self.team, project_id=self.project_id, name=unknown, last_seen_at=None)
        for event in (stale, fresh, unknown):
            self.add_row(event, "$browser")

        with connection.cursor() as cursor:
            units = list(discover_retention_units(cursor, self.config))

        assert [u.key for u in units] == [(stale,)]
        assert self.run_units(units) == 1
        assert self.rows() == {f"{fresh}:$browser", f"{unknown}:$browser"}

    def test_retention_candidates_are_paged_by_name(self):
        for name in ("a_event", "b_event", "c_event", "d_event", "e_event"):
            EventDefinition.objects.create(
                team=self.team, project_id=self.project_id, name=name, last_seen_at=REAL_NOW - timedelta(days=400)
            )
        config = replace_config(self.config, retention_event_batch=2)

        with connection.cursor() as cursor:
            units = list(discover_retention_units(cursor, config))

        assert [u.key for u in units] == [("a_event", "b_event"), ("c_event", "d_event"), ("e_event",)]

    def test_pollution_still_cleans_paying_orgs_but_retention_skips_them(self):
        # Pollution rows are never real data, so a paying org gets them removed too. Retention
        # deletes rows for events that really happened, so skip_paying_orgs still guards it.
        self.team.organization.has_active_subscription = True
        self.team.organization.save()
        self.add_propdef("$initial_os", PropertyDefinition.Type.PERSON)
        self.add_row("$pageview", "$initial_os")
        EventDefinition.objects.create(
            team=self.team, project_id=self.project_id, name="stale", last_seen_at=REAL_NOW - timedelta(days=400)
        )
        config = replace_config(self.config, skip_paying_orgs=True)

        with connection.cursor() as cursor:
            pollution = list(discover_pollution_units(cursor, config))
            retention = list(discover_retention_units(cursor, config))

        assert len(pollution) == 1
        assert retention == []

    def test_dormant_delete_removes_the_tenants_rows(self):
        # The statement carries no predicate beyond the tenant on purpose: re-checking dormancy per
        # batch measured ~8s against a 60s statement_timeout. `still_dormant` guards it out of band.
        self.add_row("$pageview", "$browser")
        unit = WorkUnit(
            mode="dormant", team_id=self.team.id, project_id=self.project_id, key="*", est_rows=1, reason=""
        )

        assert self.run_units([unit]) == 1
        assert self.rows() == set()

    def test_never_delete_team_ids_removes_the_team_from_discovery(self):
        self.add_propdef("$initial_referrer", PropertyDefinition.Type.PERSON)
        self.add_row("$pageview", "$initial_referrer")
        config = replace_config(self.config, never_delete_team_ids=[self.team.id])

        assert self.discover_pollution(config) == []

    @parameterized.expand(
        [
            ("stale_and_quiet", 400, 0, True),
            ("recent_event_definition", 10, 0, False),
            ("recent_clickhouse_events", 400, 5, False),
            ("clickhouse_unavailable", 400, None, False),
        ]
    )
    def test_still_dormant_recheck(self, _name: str, age_days: int, recent_events: int | None, expected: bool):
        EventDefinition.objects.create(
            team=self.team, project_id=self.project_id, name="e", last_seen_at=REAL_NOW - timedelta(days=age_days)
        )

        with connection.cursor() as cursor:
            assert still_dormant(cursor, self.team.id, 180, lambda *_: recent_events) is expected


def replace_config(config: EventPropertyCleanupConfig, **overrides: Any) -> EventPropertyCleanupConfig:
    return EventPropertyCleanupConfig(**{**config.model_dump(), **overrides})


@pytest.mark.django_db(transaction=True)
class TestJobWiring:
    def seed_team(self) -> Team:
        org = Organization.objects.create(name="eventproperty-cleanup-job")
        team = Team.objects.create(organization=org, name="eventproperty-cleanup-job")
        PropertyDefinition.objects.create(
            team=team, project_id=team.project_id, name="$initial_os", type=PropertyDefinition.Type.PERSON
        )
        EventProperty.objects.create(team=team, project_id=team.project_id, event="$pageview", property="$initial_os")
        return team

    def run_job(self, instance: Any = None, **config: Any) -> dict[str, int]:
        result = ops.eventproperty_cleanup_job.execute_in_process(
            run_config={"skip_paying_orgs": False, **config},
            resources={"cluster": MagicMock(), "persons_database_url": "postgresql://unused/never-opened"},
            instance=instance,
        )
        assert result.success
        return result.output_for_node("collect_and_vacuum_op")

    def mode_result(self, instance: Any, **config: Any) -> Any:
        result = ops.eventproperty_cleanup_job.execute_in_process(
            run_config={"skip_paying_orgs": False, **config},
            resources={"cluster": MagicMock(), "persons_database_url": "postgresql://unused/never-opened"},
            instance=instance,
        )
        assert result.success
        return result.output_for_node("run_pollution_op")

    def test_a_live_run_records_a_resume_point_and_the_next_run_starts_above_it(self):
        # The ops wiring is what the unit tests cannot reach: every other job test pins team_ids,
        # which skips the range walk entirely and so never records anything.
        team = self.seed_team()
        with dagster.DagsterInstance.ephemeral() as instance:
            first = self.mode_result(instance, dry_run=False, vacuum=False)
            recorded = read_resume_point(instance, "pollution")

            assert first.units == 1
            assert first.rows_deleted == 1
            assert recorded.last_completed_team_id > 0
            assert EventProperty.objects.filter(team=team).count() == 0

            # Everything at or below the recorded point is skipped, so a second pass finds nothing.
            second = self.mode_result(instance, dry_run=False, vacuum=False)
            assert second.units == 0
            assert read_resume_point(instance, "pollution").last_completed_team_id == (recorded.last_completed_team_id)

    def test_a_dry_run_leaves_the_resume_point_untouched(self):
        self.seed_team()
        with dagster.DagsterInstance.ephemeral() as instance:
            result = self.mode_result(instance)

            assert result.units == 1
            assert result.rows_deleted == 0
            assert read_resume_point(instance, "pollution") == START

    def test_retention_never_records_a_resume_point(self):
        # A retention unit can end early with rows for its other event names still eligible, so
        # recording its range would skip them for good.
        self.seed_team()
        with dagster.DagsterInstance.ephemeral() as instance:
            self.run_job(instance=instance, dry_run=False, vacuum=False, retention_days=180)

            assert read_resume_point(instance, "retention") == START

    def test_default_config_is_a_dry_run_that_deletes_nothing(self):
        team = self.seed_team()

        summary = self.run_job(team_ids=[team.id])

        assert EventProperty.objects.filter(team=team).count() == 1
        assert summary["units"] == 1
        assert summary["rows_deleted"] == 0

    def test_live_run_deletes_through_the_sequential_ops(self):
        team = self.seed_team()

        summary = self.run_job(team_ids=[team.id], dry_run=False, vacuum=False)

        assert EventProperty.objects.filter(team=team).count() == 0
        assert summary["rows_deleted"] == 1
        assert summary["vacuums"] == 0

    def test_live_run_skips_preflight_vacuum_without_debt_and_vacuums_once_at_the_end(self):
        team = self.seed_team()

        summary = self.run_job(team_ids=[team.id], dry_run=False, vacuum=True)

        assert EventProperty.objects.filter(team=team).count() == 0
        assert summary["vacuums"] == 1
