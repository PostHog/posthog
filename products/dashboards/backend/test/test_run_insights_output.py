from datetime import date

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.constants import RUN_INSIGHTS_MAX_TOTAL_CHARS, RUN_INSIGHTS_MIN_TILE_CHARS
from products.dashboards.backend.run_insights_output import (
    bound_formatted_result,
    parse_max_result_chars,
    parse_tile_ids,
    render_unsupported_result,
    tile_budget,
    tile_fits_response_budget,
)


def _table(rows: int) -> str:
    return "\n".join(["Date|Count", *(f"2026-01-01 {row:02d}:00|{row}" for row in range(rows))])


class TestBoundFormattedResult(SimpleTestCase):
    @parameterized.expand([("table_fits_the_budget", 10_000), ("zero_means_no_limit", 0)])
    def test_returns_the_table_unchanged(self, _name: str, max_chars: int) -> None:
        table = _table(3)

        self.assertEqual(bound_formatted_result(table, tile_id=7, max_chars=max_chars), table)

    def test_keeps_the_newest_rows_and_not_only_the_oldest(self) -> None:
        # Trends tables run oldest bucket first, so a head-only cut reads as the whole date range.
        table = _table(60)

        bounded = bound_formatted_result(table, tile_id=7, max_chars=300).splitlines()

        self.assertEqual(bounded[0], "Date|Count")
        self.assertEqual(bounded[1], table.splitlines()[1])
        self.assertEqual(bounded[-1], table.splitlines()[-1])

    def test_holds_every_kept_row_within_the_budget(self) -> None:
        bounded = bound_formatted_result(_table(60), tile_id=7, max_chars=300).splitlines()

        rows = [line for line in bounded if not line.startswith("[")]
        self.assertLessEqual(sum(len(row) + 1 for row in rows), 300)

    def test_names_the_tile_and_how_many_rows_it_dropped(self) -> None:
        bounded = bound_formatted_result(_table(60), tile_id=7, max_chars=300).splitlines()

        note = next(line for line in bounded if line.startswith("["))
        self.assertIn(f"{60 - (len(bounded) - 2)} of 60 rows omitted", note)
        self.assertIn("tile_ids=7", note)

    @parameterized.expand(
        [
            # One long row must still be cut, otherwise a wide table bypasses the budget entirely.
            ("single_row_wider_than_the_budget", "x" * 500, 50),
            ("header_wider_than_the_budget", _table(20), 6),
        ]
    )
    def test_cuts_text_it_cannot_hold_by_whole_rows(self, _name: str, formatted: str, max_chars: int) -> None:
        bounded = bound_formatted_result(formatted, tile_id=7, max_chars=max_chars)

        self.assertEqual(bounded.splitlines()[0], formatted[:max_chars])
        self.assertIn("tile_ids=7", bounded)


class TestParseQueryParams(SimpleTestCase):
    @parameterized.expand([("missing", None), ("blank", "  ")])
    def test_tile_ids_selects_nothing(self, _name: str, raw: str | None) -> None:
        self.assertEqual(parse_tile_ids(raw), [])

    def test_tile_ids_drops_repeats_and_keeps_request_order(self) -> None:
        # run_widgets returns its results in the order asked for, so the parser must not sort.
        self.assertEqual(parse_tile_ids(" 4, 3 ,4"), [4, 3])

    def test_max_result_chars_defaults(self) -> None:
        self.assertGreater(parse_max_result_chars(None), 0)


class TestRenderUnsupportedResult(SimpleTestCase):
    def test_renders_a_value_json_cannot_serialize(self) -> None:
        self.assertIn("2026-01-01", render_unsupported_result([{"day": date(2026, 1, 1)}]))


class TestTileBudget(SimpleTestCase):
    def test_holds_a_tile_down_to_what_the_response_has_left(self) -> None:
        # Without this a single generous max_result_chars would overshoot the whole-response budget.
        self.assertEqual(tile_budget(1_000_000, RUN_INSIGHTS_MAX_TOTAL_CHARS - 100), 100)

    def test_keeps_the_smaller_per_tile_limit(self) -> None:
        self.assertEqual(tile_budget(50, 0), 50)

    def test_zero_stays_unbounded(self) -> None:
        self.assertEqual(tile_budget(0, RUN_INSIGHTS_MAX_TOTAL_CHARS - 1), 0)

    @parameterized.expand(
        [
            ("nothing_used", 0, True),
            ("floor_exactly_left", RUN_INSIGHTS_MAX_TOTAL_CHARS - RUN_INSIGHTS_MIN_TILE_CHARS, True),
            ("below_the_floor", RUN_INSIGHTS_MAX_TOTAL_CHARS - 1, False),
        ]
    )
    def test_a_tile_needs_the_floor_to_run(self, _name: str, used_chars: int, expected: bool) -> None:
        self.assertEqual(tile_fits_response_budget(used_chars), expected)
