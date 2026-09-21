from datetime import date

from django.test import SimpleTestCase

from products.dashboards.backend.constants import RUN_INSIGHTS_MAX_TOTAL_CHARS
from products.dashboards.backend.run_insights_output import (
    parse_max_result_chars,
    parse_tile_ids,
    render_unsupported_result,
    tile_budget,
    truncate_formatted_result,
)


class TestTruncateFormattedResult(SimpleTestCase):
    def test_keeps_a_table_that_fits(self) -> None:
        table = "Date|Count\n2026-01-01|1"

        self.assertEqual(truncate_formatted_result(table, tile_id=7, max_chars=100), table)

    def test_zero_means_no_limit(self) -> None:
        table = "Date|Count\n" + "\n".join(f"2026-01-{day:02d}|1" for day in range(1, 32))

        self.assertEqual(truncate_formatted_result(table, tile_id=7, max_chars=0), table)

    def test_drops_the_rows_that_do_not_fit(self) -> None:
        table = "Date|Count\n2026-01-01|1\n2026-01-02|2\n2026-01-03|3"

        truncated = truncate_formatted_result(table, tile_id=7, max_chars=26)

        self.assertEqual(truncated.splitlines()[:2], ["Date|Count", "2026-01-01|1"])
        self.assertIn("tile_ids=7", truncated)

    def test_cuts_a_single_row_wider_than_the_budget(self) -> None:
        # One long row must still be cut, otherwise a wide table bypasses the budget entirely.
        wide_row = "x" * 500

        truncated = truncate_formatted_result(wide_row, tile_id=7, max_chars=50)

        self.assertEqual(truncated.splitlines()[0], "x" * 50)
        self.assertIn("tile_ids=7", truncated)


class TestParseQueryParams(SimpleTestCase):
    def test_tile_ids_defaults_to_every_tile(self) -> None:
        self.assertIsNone(parse_tile_ids(None))
        self.assertIsNone(parse_tile_ids("  "))

    def test_tile_ids_drops_repeats_and_spacing(self) -> None:
        self.assertEqual(parse_tile_ids(" 3, 4 ,3"), {3, 4})

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
