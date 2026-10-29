import pytest

from posthog.clickhouse.events_json import is_temporary_event_property


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
