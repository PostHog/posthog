from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.paging import PageRequest

from products.ai_observability.backend.facade.diagnostics_contracts import ErrorOrder
from products.ai_observability.backend.logic.diagnostics.error_group_queries import (
    ErrorPageRead,
    count_new_errors,
    has_any_error,
    load_error_first_seen,
    load_error_group,
    load_error_page,
)
from products.ai_observability.backend.logic.diagnostics.error_groups import ErrorCountsRow, ErrorGroupRow, ErrorView
from products.ai_observability.backend.logic.diagnostics.group_page_queries import MAX_SORTED_GROUPS
from products.ai_observability.backend.logic.diagnostics.trends import Trend
from products.ai_observability.backend.logic.traces.lookback import LOOKBACK
from products.ai_observability.backend.logic.traces.trace_metrics import BucketSize, bucket_starts
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection

from ..traces.test_trace_selection_queries import at, seed, to_selection

PERSON_A = "00000000-0000-4000-8000-0000000000a1"
PERSON_B = "00000000-0000-4000-8000-0000000000b2"
PERSON_C = "00000000-0000-4000-8000-0000000000c3"
PERSON_D = "00000000-0000-4000-8000-0000000000d4"
DAY = 24 * 60

CONTEXT = "Context window exceeded by <n> tokens"
INVALID_JSON = "Invalid JSON in tool arguments"
QUOTA = "Quota exhausted for project"
TIMED_OUT = "Request timed out after <n> ms"
UNKNOWN_TOOL = "Unknown tool <name> called"


def _flagged(message: str | None, minute: int, trace_id: str, **event: Any) -> dict[str, Any]:
    properties = {"$ai_is_error": True, **({"$ai_error_normalized": message} if message else {})}
    return {
        "event": "$ai_generation",
        "trace_id": trace_id,
        "minutes": minute,
        **event,
        "properties": {**properties, **event.get("properties", {})},
    }


def _occurrences(
    message: str, minutes: range, *, prefix: str, traces: int, persons: tuple[str, ...] = (PERSON_A,)
) -> list[dict[str, Any]]:
    return [
        _flagged(message, minute, f"{prefix}-{index % traces}", person_id=persons[index % len(persons)])
        for index, minute in enumerate(minutes)
    ]


class TestErrorGroupQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Away from UTC, a bucket floored in UTC instead of the project's zone lands half an hour off.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()

    def _selection(self, **overrides: Any) -> TraceSelection:
        return to_selection(self.team, {"date_from": 0, "date_to": 120, **overrides})

    def _page(
        self,
        selection: TraceSelection | None = None,
        *,
        search: str | None = None,
        view: ErrorView | None = None,
        order: ErrorOrder = ErrorOrder.OCCURRENCES,
        limit: int = 50,
        offset: int = 0,
    ) -> ErrorPageRead:
        return load_error_page(
            self.team,
            self.user,
            selection or self._selection(),
            search=search,
            view=view,
            order=order,
            page=PageRequest(limit=limit, offset=offset),
        )

    def _seed_trends(self) -> None:
        seed(
            self.team,
            [
                *_occurrences(CONTEXT, range(59, 71), prefix="context", traces=12),
                *_occurrences(CONTEXT, range(-60, -40, 10), prefix="context-before", traces=1),
                *_occurrences(INVALID_JSON, range(81, 91), prefix="json", traces=10, persons=(PERSON_A, PERSON_B)),
                _flagged(INVALID_JSON, -10 * DAY, "json-lookback"),
                *_occurrences(QUOTA, range(109, 111), prefix="quota", traces=2, persons=(PERSON_A, PERSON_B)),
                *_occurrences(QUOTA, range(-110, -10, 10), prefix="quota-before", traces=10),
                *_occurrences(
                    TIMED_OUT, range(96, 101), prefix="timeout", traces=5, persons=(PERSON_A, PERSON_B, PERSON_C)
                ),
                *_occurrences(TIMED_OUT, range(-100, -50, 10), prefix="timeout-before", traces=5),
                *_occurrences(
                    UNKNOWN_TOOL,
                    range(69, 81),
                    prefix="tool",
                    traces=2,
                    persons=(PERSON_A, PERSON_B, PERSON_C, PERSON_D),
                ),
            ],
        )

    def test_page_groups_flagged_events_by_message_with_previous_period_and_buckets(self) -> None:
        rate_limit = "Rate limit reached for model <model>"
        seed(
            self.team,
            [
                *(
                    _flagged(rate_limit, minute, trace_id, person_id=person, properties={"$ai_model": model})
                    for minute, trace_id, person, model in [
                        (5, "rate-1", PERSON_A, "gpt-a"),
                        (10, "rate-1", PERSON_A, "gpt-a"),
                        (20, "rate-1", PERSON_A, "gpt-b"),
                        (40, "rate-2", PERSON_B, "gpt-a"),
                        (45, "rate-2", PERSON_B, "gpt-b"),
                        (50, "rate-2", PERSON_B, "gpt-c"),
                        (95, "rate-3", PERSON_A, "gpt-a"),
                        (100, "rate-3", PERSON_A, "gpt-b"),
                        (105, "rate-3", PERSON_A, "gpt-c"),
                        (110, "rate-3", PERSON_A, "gpt-d"),
                    ]
                ),
                _flagged(rate_limit, 30, "rate-1", properties={"$ai_is_error": False}),
                _flagged(None, 31, "rate-1"),
                _flagged("Model overloaded", 60, "rate-2"),
                *_occurrences(rate_limit, range(-60, -40, 10), prefix="rate-before", traces=1),
            ],
        )

        read = self._page()

        assert read.rows[0] == ErrorGroupRow(
            message=rate_limit,
            occurrences=10,
            previous_occurrences=2,
            traces=3,
            users=2,
            models=("gpt-a", "gpt-b", "gpt-c"),
            last_seen=at(110),
            trend=Trend.INCREASING,
            series=(3, 3, 4),
        )
        assert [row.message for row in read.rows] == [rate_limit, "Model overloaded"]
        assert read.count == 2
        assert read.bucket_starts == tuple(bucket_starts(self._selection().window, BucketSize.HOUR))

    def test_users_leave_out_anonymous_distinct_ids_and_keep_otel_ids(self) -> None:
        message = "Tool call failed"
        seed(
            self.team,
            [
                _flagged(message, 10, "tool-1", distinct_id="user-a", person_id=PERSON_A),
                _flagged(message, 11, "tool-1", distinct_id="user-a", person_id=PERSON_A),
                _flagged(message, 20, "tool-2", distinct_id="tool-2", person_id=PERSON_B),
                _flagged(
                    message,
                    30,
                    "tool-3",
                    distinct_id="span-user",
                    person_id=PERSON_C,
                    properties={"$ai_ingestion_source": "otel"},
                ),
            ],
        )

        [row] = self._page().rows

        assert row.users == 2

    def test_models_break_equal_counts_by_name(self) -> None:
        seed(
            self.team,
            [
                _flagged(TIMED_OUT, 10 + index, f"model-{index}", properties={"$ai_model": model})
                for index, model in enumerate(["gpt-d", "gpt-b", "gpt-z", "gpt-c", "gpt-a", "gpt-z"])
            ],
        )

        [row] = self._page().rows

        assert row.models == ("gpt-z", "gpt-a", "gpt-b")

    @parameterized.expand([("test_accounts_filtered", True), ("test_accounts_kept", False)])
    def test_new_ignores_property_filters_and_search_but_follows_the_test_account_switch(
        self, _name: str, filter_test_accounts: bool
    ) -> None:
        self.team.test_account_filters = [
            {"key": "deployment", "value": ["staging"], "operator": "is_not", "type": "event"}
        ]
        self.team.save()
        only_now = "Timeout calling search API"
        filtered_out_before = "Timeout reading <file>"
        test_account_before = "Timeout from staging proxy"
        straddling = "Timeout in a trace that began before the range"
        gpt_a = {"properties": {"$ai_model": "gpt-a"}}
        seed(
            self.team,
            [
                _flagged(only_now, 10, "search-now", **gpt_a),
                {"event": "$ai_span", "trace_id": "straddle", "minutes": -5, **gpt_a},
                _flagged(straddling, 5, "straddle", **gpt_a),
                _flagged(filtered_out_before, 20, "reading-now", **gpt_a),
                _flagged(filtered_out_before, -10 * DAY, "reading-before", properties={"$ai_model": "gpt-z"}),
                _flagged(test_account_before, 30, "staging-now", **gpt_a),
                _flagged(
                    test_account_before,
                    -10 * DAY,
                    "staging-before",
                    properties={"$ai_model": "gpt-a", "deployment": "staging"},
                ),
            ],
        )
        selection = self._selection(
            properties=[{"key": "$ai_model", "value": "gpt-a", "operator": "exact", "type": "event"}],
            filter_test_accounts=filter_test_accounts,
        )
        expected = {only_now, straddling, *([test_account_before] if filter_test_accounts else [])}

        read = self._page(selection, search="TIMEOUT", view=ErrorView.NEW)
        new_count = count_new_errors(self.team, self.user, selection, search="TIMEOUT")

        assert {row.message for row in read.rows} == expected
        assert (read.count, new_count) == (len(expected), len(expected))

    @parameterized.expand(
        [
            ("increasing", [CONTEXT, UNKNOWN_TOOL, INVALID_JSON], Trend.INCREASING),
            ("decreasing", [QUOTA], Trend.DECREASING),
            ("new", [UNKNOWN_TOOL], Trend.INCREASING),
        ]
    )
    def test_each_view_and_the_counts_agree_with_the_trend_whether_new_or_not(
        self, view: ErrorView, expected: list[str], trend: Trend
    ) -> None:
        self._seed_trends()

        read = self._page(view=view)

        assert read.counts == ErrorCountsRow(total=5, increasing=3, decreasing=1, max_occurrences=12)
        assert [row.message for row in read.rows] == expected
        assert read.count == len(expected)
        assert {row.trend for row in read.rows} == {trend}

    def test_the_support_rule_drops_impersonated_rows_but_their_events_still_place_the_trace(self) -> None:
        impersonated = {"ai_support_impersonated": True}
        seed(
            self.team,
            [
                _flagged(TIMED_OUT, 20, "support-session", properties=impersonated),
                _flagged(TIMED_OUT, -5, "helped"),
                {"event": "$ai_span", "trace_id": "helped", "minutes": 10, "properties": impersonated},
            ],
        )

        [row] = self._page().rows

        assert (row.occurrences, row.previous_occurrences, row.traces, row.last_seen) == (1, 0, 1, at(-5))

    @parameterized.expand(
        [
            ("occurrences", [CONTEXT, UNKNOWN_TOOL, INVALID_JSON, TIMED_OUT, QUOTA]),
            ("change", [UNKNOWN_TOOL, INVALID_JSON, CONTEXT, TIMED_OUT, QUOTA]),
            ("traces", [CONTEXT, INVALID_JSON, TIMED_OUT, QUOTA, UNKNOWN_TOOL]),
            ("users", [UNKNOWN_TOOL, TIMED_OUT, INVALID_JSON, QUOTA, CONTEXT]),
            ("last_seen", [QUOTA, TIMED_OUT, INVALID_JSON, UNKNOWN_TOOL, CONTEXT]),
        ]
    )
    def test_order_change_then_message_is_stable_across_pages(self, order: ErrorOrder, expected: list[str]) -> None:
        self._seed_trends()

        pages = [self._page(order=order, limit=2, offset=offset) for offset in (0, 2, 4)]

        assert [row.message for page in pages for row in page.rows] == expected
        assert {page.count for page in pages} == {5}

    def test_an_offset_past_the_sorted_groups_reads_an_empty_page_with_counts(self) -> None:
        self._seed_trends()

        read = self._page(offset=MAX_SORTED_GROUPS + 1)

        assert read.rows == ()
        assert read.count == 5
        assert read.counts == ErrorCountsRow(total=5, increasing=3, decreasing=1, max_occurrences=12)

    def test_group_reads_one_message_with_the_previous_series(self) -> None:
        self._seed_trends()
        [page_row] = [row for row in self._page().rows if row.message == CONTEXT]

        detail = load_error_group(self.team, self.user, self._selection(), CONTEXT)

        assert detail is not None
        assert detail.row == page_row
        assert detail.previous_series == (0, 2, 0)
        assert load_error_group(self.team, self.user, self._selection(), "Never raised") is None

    @parameterized.expand(
        [
            ("ascii", "rate limit", ["Embeddings RATE LIMIT hit", "Rate limit reached"]),
            ("accented", "LÍMITE", ["Límite de cuota superado"]),
        ]
    )
    def test_search_matches_message_ignoring_case(self, _name: str, search: str, expected: list[str]) -> None:
        seed(
            self.team,
            [
                _flagged(message, 10 + index, f"search-{index}")
                for index, message in enumerate(
                    ["Rate limit reached", "Embeddings RATE LIMIT hit", "Límite de cuota superado", "Timeout"]
                )
            ],
        )

        read = self._page(search=search)

        assert [row.message for row in read.rows] == expected
        assert read.counts.total == len(expected)

    def test_first_seen_is_the_earliest_occurrence_from_the_lookback_start(self) -> None:
        lookback_start = -int(LOOKBACK / timedelta(minutes=1))
        seed(
            self.team,
            [
                _flagged("Stale cache entry", lookback_start - 1, "stale-unchecked"),
                _flagged("Stale cache entry", lookback_start, "stale-before"),
                _flagged("Stale cache entry", 5, "stale-now"),
                _flagged("Schema mismatch", -5 * DAY, "schema-before"),
                _flagged("Schema mismatch", 6, "schema-now"),
                _flagged("Only in range", 7, "only-now"),
            ],
        )

        first_seen = load_error_first_seen(
            self.team,
            self.user,
            self._selection(),
            ["Stale cache entry", "Schema mismatch", "Only in range", "Never raised"],
        )

        assert first_seen == {
            "Stale cache entry": at(lookback_start),
            "Schema mismatch": at(-5 * DAY),
            "Only in range": at(7),
        }

    @parameterized.expand([("inside_the_lookback", 20, True), ("past_the_lookback", 40, False)])
    def test_any_error_looks_back_from_the_range(self, _name: str, days_before: int, expected: bool) -> None:
        seed(self.team, [_flagged("Upstream refused the request", -days_before * DAY, "refused")])

        assert has_any_error(self.team, self.user, self._selection()) is expected
