"""Executable checks for the declarative metric catalog.

Every `Case` in the catalog runs through the production compiler against
real ClickHouse — the same fused SQL the workflow executes, asserted on a
fresh team. A wrong condition, a broken dedup expression, or a boundary
off-by-one in `compiler.py` fails here with the metric and case named.

The parity test pins the fused scan against the legacy per-metric queries
on identical data; it exists for the v1→v2 migration window and dies with v1.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.models import Team
from posthog.models.event.util import create_event
from posthog.tasks.usage_report import (
    get_teams_with_billable_enhanced_persons_event_count_in_period,
    get_teams_with_billable_event_count_in_period,
    get_teams_with_event_count_with_groups_in_period,
)
from posthog.temporal.usage_report.catalog import EVENTS_METRICS, EventFixture
from posthog.temporal.usage_report.compiler import run_events_family

PERIOD_START = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC)


def _insert(team: Team, fixtures: tuple[EventFixture, ...], distinct_id: str) -> None:
    dup_uuids: dict[str, UUID] = {}
    for fixture in fixtures:
        create_event(
            event_uuid=dup_uuids.setdefault(fixture.dup, uuid4()) if fixture.dup else uuid4(),
            event=fixture.event,
            team=team,
            distinct_id=distinct_id,
            timestamp=PERIOD_START + timedelta(hours=fixture.at_hours),
            properties=dict(fixture.properties),
            person_mode=fixture.person_mode,  # type: ignore[arg-type]
        )


def _team_value(results: dict[str, list[tuple[int, int]]], metric_name: str, team_id: int) -> int:
    return dict(results[metric_name]).get(team_id, 0)


def test_every_metric_declares_cases() -> None:
    missing = [metric.name for metric in EVENTS_METRICS if not metric.cases]
    assert not missing, f"Catalog metrics without pinned cases (we bill for untested semantics): {missing}"


class TestEventsCatalogCases(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            (f"{metric.name}_{index}_{case.note or 'case'}", metric.name, case)
            for metric in EVENTS_METRICS
            for index, case in enumerate(metric.cases)
        ]
    )
    def test_case(self, _name: str, metric_name: str, case) -> None:
        team = Team.objects.create(organization=self.organization)
        _insert(team, case.given, distinct_id="catalog-case")

        results = run_events_family(PERIOD_START, PERIOD_END)

        assert _team_value(results, metric_name, team.id) == case.expect, case.note


class TestEventsFamilyLegacyParity(ClickhouseTestMixin, BaseTest):
    def test_compiled_family_matches_legacy_queries(self) -> None:
        team = Team.objects.create(organization=self.organization)
        for index, metric in enumerate(EVENTS_METRICS):
            for case in metric.cases:
                _insert(team, case.given, distinct_id=f"parity-{index}")

        compiled = run_events_family(PERIOD_START, PERIOD_END)
        legacy = {
            "event_count_in_period": get_teams_with_billable_event_count_in_period(
                PERIOD_START, PERIOD_END, count_distinct=True
            ),
            "enhanced_persons_event_count_in_period": get_teams_with_billable_enhanced_persons_event_count_in_period(
                PERIOD_START, PERIOD_END, count_distinct=True
            ),
            "event_count_with_groups_in_period": get_teams_with_event_count_with_groups_in_period(
                PERIOD_START, PERIOD_END
            ),
        }

        for metric_name, legacy_rows in legacy.items():
            assert _team_value(compiled, metric_name, team.id) == dict(legacy_rows).get(team.id, 0), (
                f"Fused scan and legacy query disagree on {metric_name}"
            )
