import os
import time
from contextlib import contextmanager

import unittest

from parameterized import parameterized

from common.hogvm.python.stl.date import date_string_to_seconds, toDate, toDateTime, toUnixTimestamp

# The shared date-like grammar. The canonical spec lives above `parse_datetime_to_seconds` in
# `rust/common/hogvm/src/stl.rs`; the same table is driven by `rust/common/hogvm/tests/datetime.rs`
# and `common/hogvm/typescript/src/__tests__/date.test.ts`. All three must agree — before this was
# pinned, only 4 of the original 34 of these inputs produced the same answer in all three VMs.
ACCEPTED = [
    ("2024-01-01", 1704067200),
    ("2024-01-01T00:00:00Z", 1704067200),
    ("2024-01-01t00:00:00z", 1704067200),  # RFC3339 says the designators are case-insensitive
    ("2024-01-01T00:00:00.000Z", 1704067200),
    ("2024-01-01T00:00:00", 1704067200),  # naive => UTC, never the host zone
    ("2024-01-01 00:00:00", 1704067200),  # the ClickHouse form HogQL emits
    ("2024-01-01T00:00", 1704067200),
    ("2024-01-01T00:00:00+05:00", 1704049200),
    ("2024-01-01 00:00:00+05:00", 1704049200),
    ("2024-01-01T00:00:00-0500", 1704085200),  # offset without the colon
    ("2024-01-01T00:00:00.123Z", 1704067200.123),
    ("2024-01-01T00:00:00.123456Z", 1704067200.123),  # truncated to ms, not rounded
    ("  2024-01-01  ", 1704067200),
    ("2024-01-01T00:00:00+05", 1704049200),  # offset hours only
    ("2024-01-01T00:00:00,123Z", 1704067200.123),  # comma fraction separator
    ("1960-01-01T00:00:00.123Z", -315619199.877),  # pre-epoch: truncation must not flip sign
]

REJECTED = [
    "2024",  # luxon accepted these five as instants; a string property could plausibly hold any
    "2024-01",
    "20240101",  # `fromisoformat` accepted this and `2024-W05`; the other two VMs never did
    "2024-W05",
    "2024-001",
    "12:30",  # luxon resolved this against *today's* date
    "1700000000",  # only Rust accepted this, and now only via its explicit native (see its tests)
    "not-a-date",
    "",
    "2024-13-01",
    "2024-02-30",
    "2024-01-01T24:00:00Z",  # luxon normalized hour 24 to the next midnight; the others rejected
    "2024-01-01T00:00.123Z",  # a fraction requires seconds; luxon rejected what the others took
    "2024-01-01T00:00:00+24:00",  # made Python datetime.timezone RAISE out of the comparison path
    "2024-01-01T00:00:00+99:99",  # same
    "0000-01-01",  # valid to chrono and luxon, not to Python datetime
    "2024-01-01T25:00:00Z",  # out-of-range hour
    "2024-01-01T00:60:00Z",  # out-of-range minute
    "٢٠٢٤-٠١-٠١",  # Unicode digits. \d matches them in the Python/Rust regex engines (never in JS),
    # and int() parses them, so this was a valid instant here and rejected by the other two VMs...
    "2024-01-01T00:00+0١",  # ...and these two byte-sliced mid-codepoint in Rust — a panic, not an error
    "2024-01-01T00:00:00.١٢Z",
]


@contextmanager
def host_timezone(zone: str):
    """Run the body as if the process were in `zone`, restoring the real one afterwards."""
    original = os.environ.get("TZ")
    os.environ["TZ"] = zone
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = original
        time.tzset()


class TestDateLikeGrammar(unittest.TestCase):
    @parameterized.expand(ACCEPTED)
    def test_accepts(self, value, expected):
        self.assertAlmostEqual(date_string_to_seconds(value), expected, places=3)
        self.assertAlmostEqual(toDateTime(value)["dt"], expected, places=3)
        self.assertAlmostEqual(toUnixTimestamp(value), expected, places=3)

    @parameterized.expand([(value,) for value in REJECTED])
    def test_rejects(self, value):
        self.assertIsNone(date_string_to_seconds(value))
        with self.assertRaises(ValueError):
            toDateTime(value)

    def test_naive_string_resolves_to_utc_regardless_of_host_timezone(self):
        # Regression: `datetime.fromisoformat(s).timestamp()` resolves a naive datetime in the
        # *host's* zone, so `toDateTime('2026-07-01')` depended on where the process was running and
        # disagreed with the TypeScript and Rust VMs (both UTC-anchored) by the local UTC offset.
        for zone in ("UTC", "America/New_York", "Asia/Tokyo"):
            with self.subTest(zone=zone), host_timezone(zone):
                self.assertEqual(toDateTime("2024-01-01")["dt"], 1704067200)
                self.assertEqual(toDateTime("2024-01-01 00:00:00")["dt"], 1704067200)
                self.assertEqual(date_string_to_seconds("2024-01-01T00:00:00"), 1704067200)
                self.assertEqual(toDate("2024-01-01"), {"__hogDate__": True, "year": 2024, "month": 1, "day": 1})

    def test_explicit_zone_applies_only_to_input_carrying_no_zone_of_its_own(self):
        self.assertEqual(toUnixTimestamp("2024-01-01 00:00:00", "America/New_York"), 1704085200)
        self.assertEqual(toUnixTimestamp("2024-01-01T00:00:00Z", "America/New_York"), 1704067200)

    def test_number_passes_through_as_epoch_seconds_without_parsing(self):
        self.assertEqual(toDateTime(1700000000)["dt"], 1700000000)

    def test_an_unusable_offset_returns_none_rather_than_escaping_the_vm(self):
        # `date_string_to_seconds` is called from `unify_comparison_types` on every comparison
        # opcode, so a bare ValueError here escapes the VM entirely instead of leaving the operands
        # uncoerced. `datetime.timezone` raises for |offset| >= 24h.
        for value in ("2024-01-01T00:00:00+24:00", "2024-01-01T00:00:00+99:99"):
            with self.subTest(value=value):
                self.assertIsNone(date_string_to_seconds(value))

    def test_ambiguous_local_time_takes_the_first_of_the_dst_fold(self):
        # 01:30 happens twice on 2024-11-03 in New York. pytz's `localize` defaults to is_dst=False
        # (the second, -05:00); Rust's `LocalResult::Ambiguous(dt, _)` and luxon both take the first
        # (-04:00), so pytz's default would land an hour off.
        self.assertEqual(toUnixTimestamp("2024-11-03 01:30:00", "America/New_York"), 1730611800)


if __name__ == "__main__":
    unittest.main()
