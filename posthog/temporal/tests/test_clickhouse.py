import uuid
import datetime as dt

import pytest

from posthog.clickhouse.query_tagging import QueryTags
from posthog.temporal.common.clickhouse import add_log_comment_param, encode_clickhouse_data


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
            dt.datetime(2023, 7, 14, 0, 0, 0, tzinfo=dt.UTC),
            b"toDateTime('2023-07-14 00:00:00', 'UTC')",
        ),
        (dt.datetime(2023, 7, 14, 0, 0, 0), b"toDateTime('2023-07-14 00:00:00')"),
        (
            dt.datetime(2023, 7, 14, 0, 0, 0, 5555, tzinfo=dt.UTC),
            b"toDateTime64('2023-07-14 00:00:00.005555', 6, 'UTC')",
        ),
        ([1.1666, [0.132, -0.2390], 0.0], b"[1.1666,[0.132,-0.239],0]"),
    ],
)
def test_encode_clickhouse_data(data, expected):
    """Test data is encoded as expected."""
    result = encode_clickhouse_data(data)
    assert result == expected


@pytest.mark.parametrize(
    "params,qt,want",
    [
        ({}, QueryTags(), {"log_comment": "{}"}),
        ({"param_log_comment": ""}, QueryTags(), {"param_log_comment": "", "log_comment": "{}"}),
        ({"param_log_comment": "{}"}, QueryTags(), {"param_log_comment": "{}"}),
        ({"param_log_comment": '{"kind":"qt"}'}, QueryTags(), {"param_log_comment": '{"kind":"qt"}'}),
        ({"param_log_comment": '{"kind":"xyz"}'}, QueryTags(kind="abc"), {"param_log_comment": '{"kind":"xyz"}'}),
        ({}, QueryTags(kind="abc"), {"log_comment": '{"kind":"abc"}'}),
    ],
)
def test_add_log_comment_param(params, qt, want):
    add_log_comment_param(params, qt)
    assert params == want
