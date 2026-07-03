"""Executable checks for the declarative metric catalog.

Every `Case` in the catalog runs through the production compiler against
real ClickHouse — the same fused SQL the workflow executes, asserted on a
fresh team. A wrong condition, a broken dedup expression, or a boundary
off-by-one in `compiler.py` fails here with the metric and case named.

The parity tests pin the fused scan against the legacy per-metric queries
on identical data — a fixed catalog-case union plus Hypothesis-generated
event batches; they exist for the v1→v2 migration window and die with v1.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from hypothesis import (
    given,
    settings,
    strategies as st,
)
from hypothesis.extra.django import TestCase as HypothesisTestCase
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.event.util import create_event
from posthog.tasks.usage_report import (
    get_all_event_metrics_in_period,
    get_teams_with_billable_enhanced_persons_event_count_in_period,
    get_teams_with_billable_event_count_in_period,
    get_teams_with_event_count_with_groups_in_period,
)
from posthog.temporal.usage_report.catalog import EVENTS_METRICS, EventFixture
from posthog.temporal.usage_report.compiler import run_events_family

PERIOD_START = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC)

# `get_all_event_metrics_in_period` keys most SDK metrics as `<short>` for the
# field `<short>_count_in_period`; the integration metrics are the exception.
_INTEGRATION_FIELDS = {
    f"{integration}_events": f"event_count_from_{integration}_in_period"
    for integration in ("helicone", "langfuse", "keywords_ai", "traceloop")
}


def _legacy_results(begin: datetime, end: datetime) -> dict[str, list]:
    """Every ported metric computed via the legacy v1 queries, keyed by the
    catalog metric name. Extend when porting more metrics; dies with v1.
    """
    results: dict[str, list] = {
        "event_count_in_period": get_teams_with_billable_event_count_in_period(begin, end, count_distinct=True),
        "enhanced_persons_event_count_in_period": get_teams_with_billable_enhanced_persons_event_count_in_period(
            begin, end, count_distinct=True
        ),
        "event_count_with_groups_in_period": get_teams_with_event_count_with_groups_in_period(begin, end),
    }
    for short, rows in get_all_event_metrics_in_period(begin, end).items():
        results[_INTEGRATION_FIELDS.get(short, f"{short}_count_in_period")] = rows
    return results


def _insert(team: Team, fixtures: tuple[EventFixture, ...], distinct_id: str) -> None:
    dup_uuids: dict[str, UUID] = {}
    for fixture in fixtures:
        properties = dict(fixture.properties)
        if fixture.lib is not None:
            properties["$lib"] = fixture.lib
        if fixture.ai_lib is not None:
            properties["$ai_lib"] = fixture.ai_lib
        create_event(
            event_uuid=dup_uuids.setdefault(fixture.dup, uuid4()) if fixture.dup else uuid4(),
            event=fixture.event,
            team=team,
            distinct_id=distinct_id,
            timestamp=PERIOD_START + timedelta(hours=fixture.at_hours),
            properties=properties,
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


def _assert_parity_for_team(team_id: int) -> None:
    compiled = run_events_family(PERIOD_START, PERIOD_END)
    legacy = _legacy_results(PERIOD_START, PERIOD_END)
    for metric in EVENTS_METRICS:
        assert _team_value(compiled, metric.name, team_id) == dict(legacy[metric.name]).get(team_id, 0), (
            f"Fused scan and legacy query disagree on {metric.name}"
        )


class TestEventsFamilyLegacyParity(ClickhouseTestMixin, BaseTest):
    def test_compiled_family_matches_legacy_on_catalog_cases(self) -> None:
        team = Team.objects.create(organization=self.organization)
        for index, metric in enumerate(EVENTS_METRICS):
            for case in metric.cases:
                _insert(team, case.given, distinct_id=f"parity-{index}")

        _assert_parity_for_team(team.id)


# Pools are boundary-heavy on purpose: period edges, every exclusion
# category, duplicate uuids, empty-string group values, free-text event
# names that must count as billable, and lib/ai_lib combinations that
# exercise the SDK classification (integration-prefix wins, java's two
# libs, the posthog-node AI sub-SDK carve-out).
_fixture_strategy = st.builds(
    EventFixture,
    event=st.one_of(
        st.sampled_from(
            [
                "$pageview",
                "checkout",
                "$feature_flag_called",
                "survey sent",
                "$exception",
                "$ai_generation",
                "$ai_span",
                "$conversations_loaded",
                "langfuse-trace",
                "helicone_request",
            ]
        ),
        st.text(
            alphabet=st.characters(blacklist_characters="\0", blacklist_categories=["Cs"]), min_size=1, max_size=20
        ),
    ),
    person_mode=st.sampled_from(["full", "propertyless", "force_upgrade"]),
    at_hours=st.sampled_from([-3.0, 0.0, 6.0, 12.0, 23.99, 24.0, 30.0]),
    dup=st.sampled_from([None, None, "a", "b"]),
    lib=st.sampled_from([None, "web", "js", "posthog-node", "posthog-ios", "posthog-java", "posthog-server"]),
    ai_lib=st.sampled_from([None, "posthog-openclaw", "@posthog/pi", "posthog-ai"]),
    properties=st.sampled_from([{}, {"$group_0": "org:1"}, {"$group_1": ""}, {"$group_4": "acct:9"}]),
)


class TestEventsFamilyPropertyParity(ClickhouseTestMixin, BaseTest, HypothesisTestCase):
    def setUp(self) -> None:
        super().setUp()
        # The groups metric counts raw rows, so a background merge collapsing
        # duplicate uuids between the compiled and legacy runs would flake
        # the comparison. Same guard as the legacy usage-report tests.
        sync_execute("SYSTEM STOP MERGES")
        self.addCleanup(sync_execute, "SYSTEM START MERGES")

    # `derandomize` keeps the explored examples fixed so CI is deterministic;
    # a fresh team per example isolates ClickHouse state across examples
    # (setUp does not re-run per example under `@given`).
    @given(fixtures=st.lists(_fixture_strategy, min_size=0, max_size=12))
    @settings(max_examples=20, derandomize=True, deadline=None)
    def test_fused_scan_matches_legacy_for_generated_events(self, fixtures: list[EventFixture]) -> None:
        team = Team.objects.create(organization=self.organization)
        _insert(team, tuple(fixtures), distinct_id="pbt")

        _assert_parity_for_team(team.id)
