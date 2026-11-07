import pytest

from posthog.clickhouse.events_json import decode_json_key_sql, encode_json_key, is_temporary_event_property


@pytest.mark.parametrize("reversible", [False, True])
@pytest.mark.parametrize(
    "key, legacy, reversible_key",
    [
        ("", "", ""),
        ("plain", "plain", "plain"),
        ("a.b", "a%2Eb", "a%2Eb"),
        ("a%2Eb", "a%2Eb", "a%252Eb"),
        ("discount%", "discount%", "discount%25"),
        ("%25", "%25", "%2525"),
        ("..", "%2E%2E", "%2E%2E"),
        ("%.%2E.%25", "%%2E%2E%2E%25", "%25%2E%252E%2E%2525"),
        ("é%2e", "é%2e", "é%252e"),
    ],
)
def test_encode_json_key(
    monkeypatch: pytest.MonkeyPatch, reversible: bool, key: str, legacy: str, reversible_key: str
) -> None:
    monkeypatch.setattr("posthog.clickhouse.events_json.EVENTS_JSON_REVERSIBLE_KEYS", reversible)
    assert encode_json_key(key) == (reversible_key if reversible else legacy)


@pytest.mark.parametrize(
    "reversible, expected",
    [
        (False, r"replaceAll(null_segment, '\x252E', '.')"),
        (True, r"replaceAll(replaceAll(null_segment, '\x252E', '.'), '\x2525', '\x25')"),
    ],
)
def test_decode_json_key_sql(monkeypatch: pytest.MonkeyPatch, reversible: bool, expected: str) -> None:
    monkeypatch.setattr("posthog.clickhouse.events_json.EVENTS_JSON_REVERSIBLE_KEYS", reversible)
    sql = decode_json_key_sql("null_segment")
    assert sql == expected
    assert sql % {} == expected


@pytest.mark.parametrize(
    "key, expected",
    [
        ("$set", True),
        ("$lib_custom_api_host", True),
        ("$sdk_debug_replay_flushed_size", True),
        ("$sdk_debug_current_session_duration.value", True),
        ("$set.foo", False),
        ("$sent_at", False),
        ("$sdk_debug_current_session_duration", False),
        ("custom", False),
    ],
)
def test_is_temporary_event_property(key: str, expected: bool) -> None:
    assert is_temporary_event_property(key) is expected
