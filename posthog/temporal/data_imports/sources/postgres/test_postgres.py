from datetime import date

import pytest

from posthog.temporal.data_imports.sources.postgres.postgres import SafeDateLoader


class TestSafeDateLoader:
    @pytest.fixture
    def loader(self):
        return SafeDateLoader(oid=1082)  # 1082 is the PostgreSQL OID for date type

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15", date(2024, 1, 15)),
            (b"1999-12-31", date(1999, 12, 31)),
            (b"0001-01-01", date(1, 1, 1)),
            (b"9999-12-31", date(9999, 12, 31)),
            # Edge cases: dates beyond Python's date range should clamp
            (b"48113-11-21", date.max),
            (b"10000-01-01", date.max),
            (b"99999-12-31", date.max),
            # Infinity values
            (b"infinity", date.max),
            (b"-infinity", date.min),
            # Negative years / BC dates should clamp to date.min
            (b"-0001-01-01", date.min),
            (b"-0044-03-15", date.min),
            (b"0000-01-01", date.min),
            (b"0044-03-15 BC", date.min),
            # None should return None
            (None, None),
        ],
    )
    def test_load_dates(self, loader, input_data, expected):
        assert loader.load(input_data) == expected
