import datetime as dt
import uuid

import pytest

from posthog.temporal.batch_exports.clickhouse import encode_clickhouse_data


@pytest.mark.parametrize(
    "data,expected",
    [
        (
            uuid.UUID("c4c5547d-8782-4017-8eca-3ea19f4d528e"),
            b"'c4c5547d-8782-4017-8eca-3ea19f4d528e'",
        ),
        ("", b"''"),
        ("'", b"'\\''"),
        ("\\", b"'\\\\'"),
        ("test-string", b"'test-string'"),
        ("a'\\b\\'c", b"'a\\'\\\\b\\\\\\'c'"),
        (("a", 1, ("b", 2)), b"('a',1,('b',2))"),
        (["a", 1, ["b", 2]], b"['a',1,['b',2]]"),
        (("; DROP TABLE events --",), b"('; DROP TABLE events --')"),
        (("'a'); DROP TABLE events --",), b"('\\'a\\'); DROP TABLE events --')"),
        (
            dt.datetime(2023, 7, 14, 0, 0, 0, tzinfo=dt.timezone.utc),
            b"toDateTime('2023-07-14 00:00:00', 'UTC')",
        ),
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


@pytest.mark.asyncio
async def test_stream_query_as_arrow(clickhouse_client):
    """Test asynchronously streaming a simple query as ArrowStream."""
    query = """
    SELECT
        1 AS the_one,
        '2' AS the_two,
        3.0 AS the_three
    FORMAT ArrowStream
    """
    records = [record_batch async for record_batch in clickhouse_client.stream_query_as_arrow(query)]

    assert records[0].to_pylist() == [{"the_one": 1, "the_two": "2", "the_three": 3.0}]
