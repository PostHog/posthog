import datetime as dt
import uuid

import pytest

from posthog.temporal.workflows.clickhouse import encode_clickhouse_data


@pytest.mark.parametrize(
    "data,expected",
    [
        (uuid.UUID("c4c5547d-8782-4017-8eca-3ea19f4d528e"), b"'c4c5547d-8782-4017-8eca-3ea19f4d528e'"),
        ("test-string", b"'test-string'"),
        (("a", 1, ("b", 2)), b"('a',1,('b',2))"),
        (["a", 1, ["b", 2]], b"['a',1,['b',2]]"),
        (dt.datetime(2023, 7, 14, 0, 0, 0, tzinfo=dt.timezone.utc), b"toDateTime('2023-07-14 00:00:00', 'UTC')"),
        (dt.datetime(2023, 7, 14, 0, 0, 0), b"toDateTime('2023-07-14 00:00:00')"),
        (
            dt.datetime(2023, 7, 14, 0, 0, 0, 5555, tzinfo=dt.timezone.utc),
            b"toDateTime64('2023-07-14 00:00:00.005555', 6, 'UTC')",
        ),
    ],
)
def test_encode_clickhouse_data(data, expected):
    """Test data is encoded as expected."""
    result = encode_clickhouse_data(data)
    assert result == expected
