from datetime import date

from posthog.test.base import BaseTest

from ..utils import (
    format_date,
    format_duration,
    format_matrix,
    format_number,
    format_percentage,
    replace_breakdown_labels,
    strip_datetime_seconds,
)


class TestFormatUtils(BaseTest):
    def test_format_number(self):
        assert format_number(1) == "1"
        assert format_number(1.0) == "1"
        assert format_number(1.1) == "1.1"
        assert format_number(1.123456789) == "1.12346"
        assert format_number(1.1) == "1.1"

    def test_format_number_none(self):
        assert format_number(None) == "N/A"

    def test_format_date(self):
        assert format_date(date(2025, 1, 1)) == "2025-01-01"

    def test_format_duration(self):
        assert format_duration(3661) == "1h 1m 1s"
        assert format_duration(0.5) == "500ms"
        assert format_duration(45, seconds_precision=2) == "45s"
        assert format_duration(90000, max_units=2) == "1d 1h"

    def test_format_matrix(self):
        matrix = [
            ["header1", "header2", "header3"],
            ["row1col1", "row1col2", "row1col3"],
            ["row2col1", "row2col2", "row2col3"],
        ]
        expected = "header1|header2|header3\nrow1col1|row1col2|row1col3\nrow2col1|row2col2|row2col3"
        assert format_matrix(matrix) == expected

    def test_format_matrix_empty(self):
        assert format_matrix([]) == ""

    def test_format_matrix_single_row(self):
        matrix = [["single", "row"]]
        assert format_matrix(matrix) == "single|row"

    def test_format_percentage(self):
        assert format_percentage(0.5) == "50%"
        assert format_percentage(0.123) == "12.3%"
        assert format_percentage(1.0) == "100%"
        assert format_percentage(0.0) == "0%"
        assert format_percentage(0.999) == "99.9%"
        assert format_percentage(0.1234) == "12.34%"
        assert format_percentage(0.12345) == "12.35%"  # Tests rounding

    def test_replace_breakdown_labels(self):
        # Test with breakdown other string
        assert (
            replace_breakdown_labels("test $$_posthog_breakdown_other_$$") == "test Other (i.e. all remaining values)"
        )
        # Test with breakdown null string
        assert replace_breakdown_labels("test $$_posthog_breakdown_null_$$") == "test None (i.e. no value)"
        # Test with both
        assert (
            replace_breakdown_labels("$$_posthog_breakdown_other_$$ and $$_posthog_breakdown_null_$$")
            == "Other (i.e. all remaining values) and None (i.e. no value)"
        )
        # Test with normal string
        assert replace_breakdown_labels("normal text") == "normal text"

    def test_strip_datetime_seconds(self):
        assert strip_datetime_seconds("2025-01-20") == "2025-01-20"
        assert strip_datetime_seconds("2025-01-20 00:00:00") == "2025-01-20 00:00"
        assert strip_datetime_seconds("2025-01-20 15:00") == "2025-01-20 15:00"
