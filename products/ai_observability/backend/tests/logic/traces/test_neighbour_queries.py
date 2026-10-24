import dataclasses
from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.models import Team
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.neighbour_queries import (
    Neighbours,
    load_neighbours,
    neighbour_window,
)
from products.ai_observability.backend.logic.traces.trace_listing import TraceFilters, TracePosition, TraceWindow

from .rows import T0

ANCHOR = TracePosition(trace_id="trace-b", first_timestamp=T0)
NOW = T0 + timedelta(days=1)


DEFAULT_FILTERS = TraceFilters(
    date_from=None, date_to=None, properties=(), filter_test_accounts=False, include_support_traces=False
)


def _event(team: Team, trace_id: str, timestamp: datetime, **properties: object) -> dict[str, object]:
    return {
        "event": "$ai_generation",
        "distinct_id": "user-1",
        "team": team,
        "timestamp": timestamp,
        "properties": {"$ai_trace_id": trace_id, **properties},
    }


def _ids(neighbours: Neighbours) -> tuple[str | None, str | None]:
    return (
        neighbours.older.trace_id if neighbours.older else None,
        neighbours.newer.trace_id if neighbours.newer else None,
    )


class TestNeighbourWindow(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_list_range", None, TraceWindow(start=T0 - timedelta(days=3), end=T0 + timedelta(days=3))),
            (
                "list_range_narrows_one_side",
                TraceWindow(start=T0 - timedelta(days=1), end=T0 + timedelta(days=10)),
                TraceWindow(start=T0 - timedelta(days=1), end=T0 + timedelta(days=3)),
            ),
            (
                "list_range_misses_the_trace",
                TraceWindow(start=T0 + timedelta(days=4), end=T0 + timedelta(days=5)),
                None,
            ),
        ]
    )
    def test_caps_the_list_range_around_the_trace(
        self, _name: str, list_range: TraceWindow | None, expected: TraceWindow | None
    ) -> None:
        assert neighbour_window(T0, list_range) == expected


class TestLoadNeighbours(ClickhouseTestMixin, BaseTest):
    def _load(self, **filter_overrides: Any) -> Neighbours:
        return load_neighbours(self.team, None, ANCHOR, dataclasses.replace(DEFAULT_FILTERS, **filter_overrides), NOW)

    def test_steps_by_first_event(self) -> None:
        bulk_create_events(
            [
                _event(self.team, "trace-a", T0 - timedelta(minutes=2)),
                _event(self.team, "trace-b", T0),
                _event(self.team, "trace-b", T0 + timedelta(minutes=10)),
                _event(self.team, "trace-c", T0 + timedelta(minutes=1)),
                _event(self.team, "trace-c", T0 + timedelta(minutes=20)),
            ]
        )

        neighbours = self._load()

        assert neighbours == Neighbours(
            older=TracePosition(trace_id="trace-a", first_timestamp=T0 - timedelta(minutes=2)),
            newer=TracePosition(trace_id="trace-c", first_timestamp=T0 + timedelta(minutes=1)),
        )

    def test_a_trace_that_started_before_the_anchor_is_older_even_with_later_events(self) -> None:
        bulk_create_events(
            [
                _event(self.team, "trace-d", T0 - timedelta(minutes=1)),
                _event(self.team, "trace-d", T0 + timedelta(minutes=30)),
                _event(self.team, "trace-b", T0),
            ]
        )

        assert _ids(self._load()) == ("trace-d", None)

    def test_a_trace_started_just_before_the_list_range_keeps_its_first_event(self) -> None:
        bulk_create_events(
            [
                _event(self.team, "trace-d", T0 - timedelta(minutes=2)),
                _event(self.team, "trace-d", T0 + timedelta(minutes=2)),
                _event(self.team, "trace-e", T0 - timedelta(minutes=3)),
                _event(self.team, "trace-b", T0),
            ]
        )

        assert _ids(self._load(date_from=(T0 - timedelta(minutes=1)).isoformat())) == ("trace-d", None)

    def test_ties_on_first_event_order_by_trace_id(self) -> None:
        bulk_create_events([_event(self.team, trace_id, T0) for trace_id in ("trace-a", "trace-b", "trace-c")])

        assert _ids(self._load()) == ("trace-a", "trace-c")

    def test_no_neighbours_when_the_window_holds_only_this_trace(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        bulk_create_events(
            [
                _event(self.team, "trace-b", T0),
                _event(self.team, "trace-old", T0 - timedelta(days=4)),
                _event(other_team, "trace-a", T0 - timedelta(minutes=1)),
                _event(other_team, "trace-c", T0 + timedelta(minutes=1)),
            ]
        )

        assert self._load() == Neighbours(older=None, newer=None)

    def test_window_is_empty_when_the_url_range_misses_the_trace(self) -> None:
        bulk_create_events([_event(self.team, "trace-a", T0 - timedelta(minutes=1)), _event(self.team, "trace-b", T0)])

        assert self._load(date_from=(T0 + timedelta(days=10)).isoformat()) == Neighbours(older=None, newer=None)

    def test_property_filters_decide_membership(self) -> None:
        bulk_create_events(
            [
                _event(self.team, "trace-a", T0 - timedelta(minutes=1)),
                _event(self.team, "trace-b", T0),
                _event(self.team, "trace-c", T0 + timedelta(minutes=1), plan="pro"),
            ]
        )
        pro = EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT)

        assert _ids(self._load(properties=(pro,))) == (None, "trace-c")

    def test_property_filters_pick_traces_but_the_first_event_of_any_kind_orders_them(self) -> None:
        bulk_create_events(
            [
                _event(self.team, "trace-b", T0, plan="pro"),
                _event(self.team, "trace-x", T0 - timedelta(minutes=1)),
                _event(self.team, "trace-x", T0 + timedelta(minutes=1), plan="pro"),
            ]
        )
        pro = EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT)

        assert self._load(properties=(pro,)) == Neighbours(
            older=TracePosition(trace_id="trace-x", first_timestamp=T0 - timedelta(minutes=1)), newer=None
        )

    def test_the_trace_is_never_its_own_neighbour_when_filters_skip_its_first_event(self) -> None:
        bulk_create_events(
            [
                _event(self.team, "trace-b", T0),
                _event(self.team, "trace-b", T0 + timedelta(seconds=5), plan="pro"),
            ]
        )
        pro = EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT)

        assert self._load(properties=(pro,)) == Neighbours(older=None, newer=None)

    @parameterized.expand([("hidden", False, None), ("shown_to_impersonated_sessions", True, "trace-a")])
    def test_support_traces(self, _name: str, include_support_traces: bool, expected_older: str | None) -> None:
        bulk_create_events(
            [
                _event(self.team, "trace-a", T0 - timedelta(minutes=1), ai_support_impersonated="true"),
                _event(self.team, "trace-b", T0),
            ]
        )

        assert _ids(self._load(include_support_traces=include_support_traces)) == (expected_older, None)

    def test_respects_test_account_filters(self) -> None:
        self.team.test_account_filters = [{"key": "internal", "value": ["true"], "operator": "is_not", "type": "event"}]
        self.team.save()
        bulk_create_events(
            [
                _event(self.team, "trace-a", T0 - timedelta(minutes=1), internal="true"),
                _event(self.team, "trace-b", T0),
            ]
        )

        assert _ids(self._load(filter_test_accounts=True)) == (None, None)
        assert _ids(self._load(filter_test_accounts=False)) == ("trace-a", None)
