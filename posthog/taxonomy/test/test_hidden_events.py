import pytest

from posthog.taxonomy.hidden_events import added_hidden_event


@pytest.mark.parametrize(
    "new_event_names,existing_event_names,expected",
    [
        (["$pageview", "$feature_flag_called"], [], "$feature_flag_called"),
        (["$feature_flag_called", "$feature_flag_called"], ["$feature_flag_called"], "$feature_flag_called"),
        (["$feature_flag_called", "$pageview"], ["$feature_flag_called"], None),
        ([], ["$feature_flag_called"], None),
        (["$pageview", None, 42], [], None),
    ],
    ids=["new_reference", "second_reference", "kept_reference", "dropped_reference", "no_hidden_event"],
)
def test_added_hidden_event(
    new_event_names: list[object], existing_event_names: list[object], expected: str | None
) -> None:
    assert added_hidden_event(new_event_names, existing_event_names) == expected
