from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.db.utils import DatabaseError

from parameterized import parameterized

from posthog.dags.eventproperty_cleanup import ops
from posthog.dags.eventproperty_cleanup.config import EventPropertyCleanupConfig
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
HEALTHY = HealthProbe(dead_tuple_ratio=0.0, blocked_propdefs_backends=0)
UNHEALTHY = HealthProbe(dead_tuple_ratio=0.5, blocked_propdefs_backends=0)
POLLUTION_UNIT = WorkUnit(
    mode="pollution", team_id=1, project_id=1, key="$initial_geoip_city_name", est_rows=5, reason=""
)


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

    def delete_batch(self, statement: str, params: dict[str, Any], lock_timeout: str, statement_timeout: str) -> int:
        self.delete_calls.append(params)
        outcome = self.batches.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def probe_health(self) -> HealthProbe:
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
        assert backend.delete_calls[0]["property"] == "$initial_geoip_city_name"

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
        engine, sleeps = make_engine(backend, pause_seconds=30)

        result = engine.run_unit(POLLUTION_UNIT)

        assert result.pauses == 2
        assert sleeps.count(30) == 2
        assert result.rows_deleted == 107

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
        assert chunks == [[3, 4], [11]]

    def test_explicit_team_ids_skip_the_range_walk(self):
        cursor = MagicMock()
        config = EventPropertyCleanupConfig(team_ids=[9, 2])

        assert list(iter_team_chunks(cursor, config, "UNIVERSE", {})) == [[2, 9]]
        cursor.execute.assert_not_called()


class TestDeleteStatement:
    def test_retention_unit_requires_retention_days(self):
        unit = WorkUnit(mode="retention", team_id=1, project_id=1, key=("a", "b"), est_rows=0, reason="")
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

    def test_pollution_deletes_person_only_properties_and_keeps_event_properties(self):
        self.add_propdef("$initial_geoip_city_name", PropertyDefinition.Type.PERSON)
        self.add_propdef("$browser", PropertyDefinition.Type.EVENT)
        self.add_propdef("$browser", PropertyDefinition.Type.PERSON)
        self.add_row("$pageview", "$initial_geoip_city_name")
        self.add_row("signup", "$initial_geoip_city_name")
        self.add_row("$pageview", "$browser")

        with connection.cursor() as cursor:
            units = list(discover_pollution_units(cursor, self.config))

        assert [(u.team_id, u.key) for u in units] == [(self.team.id, "$initial_geoip_city_name")]
        assert self.run_units(units) == 2
        assert self.rows() == {"$pageview:$browser"}

    def test_pollution_delete_recheck_keeps_rows_when_event_definition_appears_late(self):
        self.add_propdef("plan", PropertyDefinition.Type.PERSON)
        self.add_row("upgrade", "plan")
        with connection.cursor() as cursor:
            units = list(discover_pollution_units(cursor, self.config))
        assert len(units) == 1

        self.add_propdef("plan", PropertyDefinition.Type.EVENT)

        assert self.run_units(units) == 0
        assert self.rows() == {"upgrade:plan"}

    def test_retention_deletes_stale_events_only(self):
        stale, fresh, unknown = "old_event", "new_event", "unknown_event"
        EventDefinition.objects.create(
            team=self.team, project_id=self.project_id, name=stale, last_seen_at=NOW - timedelta(days=400)
        )
        EventDefinition.objects.create(team=self.team, project_id=self.project_id, name=fresh, last_seen_at=NOW)
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
                team=self.team, project_id=self.project_id, name=name, last_seen_at=NOW - timedelta(days=400)
            )
        config = replace_config(self.config, retention_event_batch=2)

        with connection.cursor() as cursor:
            units = list(discover_retention_units(cursor, config))

        assert [u.key for u in units] == [("a_event", "b_event"), ("c_event", "d_event"), ("e_event",)]

    def test_never_delete_team_ids_removes_the_team_from_discovery(self):
        self.add_propdef("$initial_referrer", PropertyDefinition.Type.PERSON)
        self.add_row("$pageview", "$initial_referrer")
        config = replace_config(self.config, never_delete_team_ids=[self.team.id])

        with connection.cursor() as cursor:
            assert list(discover_pollution_units(cursor, config)) == []

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
            team=self.team, project_id=self.project_id, name="e", last_seen_at=NOW - timedelta(days=age_days)
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

    def run_job(self, **config: Any) -> dict[str, int]:
        result = ops.eventproperty_cleanup_job.execute_in_process(
            run_config={"skip_paying_orgs": False, **config},
            resources={"cluster": MagicMock(), "persons_database_reader": MagicMock()},
        )
        assert result.success
        return result.output_for_node("collect_and_vacuum_op")

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
