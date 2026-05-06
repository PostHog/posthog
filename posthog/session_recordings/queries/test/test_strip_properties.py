from parameterized import parameterized

from posthog.schema import (
    CohortPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    RecordingPropertyFilter,
    SessionPropertyFilter,
)

from posthog.session_recordings.queries.utils import (
    UnexpectedQueryProperties,
    _strip_person_and_event_and_cohort_properties,
    is_recording_property,
    is_session_property,
)
from posthog.types import AnyPropertyFilter


class TestStripProperties:
    @parameterized.expand(
        [
            (
                "session entry referring domain is stripped (not unexpected)",
                SessionPropertyFilter(
                    key="$entry_referring_domain", operator=PropertyOperator.EXACT, value="example.com"
                ),
            ),
            (
                "session channel type is stripped",
                SessionPropertyFilter(key="$channel_type", operator=PropertyOperator.EXACT, value="Direct"),
            ),
            (
                "session duration is stripped",
                SessionPropertyFilter(key="$session_duration", operator=PropertyOperator.GT, value=60),
            ),
            (
                "recording console_error_count is stripped",
                RecordingPropertyFilter(key="console_error_count", operator=PropertyOperator.GT, value=0),
            ),
            (
                "hogql session.properties reference is stripped",
                HogQLPropertyFilter(key="session.properties.$channel_type = 'Direct'"),
            ),
        ]
    )
    def test_strip_keeps_nothing_for_replay_scoped_filter(self, _name: str, replay_filter: AnyPropertyFilter) -> None:
        # These filter types are handled correctly by property_to_expr(..., scope="replay"),
        # so they must not be returned as "remaining" (which would trigger UnexpectedQueryProperties).
        assert _strip_person_and_event_and_cohort_properties([replay_filter]) == []

    def test_strip_preserves_truly_unexpected_properties(self) -> None:
        unexpected = HogQLPropertyFilter(key="some_unrelated_hogql_expression = 1")
        result = _strip_person_and_event_and_cohort_properties([unexpected])
        assert result == [unexpected]

    def test_strip_removes_person_event_group_cohort_but_keeps_unknown(self) -> None:
        person = PersonPropertyFilter(key="email", operator=PropertyOperator.EXACT, value="a@b.com")
        event = EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")
        group = GroupPropertyFilter(key="org", operator=PropertyOperator.EXACT, value="ph", group_type_index=0)
        cohort = CohortPropertyFilter(key="id", value=1)
        session = SessionPropertyFilter(key="$channel_type", operator=PropertyOperator.EXACT, value="Direct")
        recording = RecordingPropertyFilter(key="console_error_count", operator=PropertyOperator.GT, value=0)
        unexpected = HogQLPropertyFilter(key="unrelated = 1")

        result = _strip_person_and_event_and_cohort_properties(
            [person, event, group, cohort, session, recording, unexpected]
        )
        assert result == [unexpected]

    def test_is_session_property_matches_type_and_hogql(self) -> None:
        assert is_session_property(
            SessionPropertyFilter(key="$entry_pathname", operator=PropertyOperator.EXACT, value="/")
        )
        assert is_session_property(HogQLPropertyFilter(key="session.properties.$channel_type = 'Direct'"))
        assert not is_session_property(
            PersonPropertyFilter(key="email", operator=PropertyOperator.EXACT, value="a@b.com")
        )

    def test_is_recording_property_matches_type(self) -> None:
        assert is_recording_property(
            RecordingPropertyFilter(key="console_error_count", operator=PropertyOperator.GT, value=0)
        )
        assert not is_recording_property(
            EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")
        )

    def test_unexpected_query_properties_message_does_not_contain_raw_value(self) -> None:
        # The exception used to embed the filter value directly, so every distinct
        # domain/url/etc. produced a brand-new error-tracking fingerprint. We now
        # summarize each filter to its type/key/operator only.
        offending_value = "www.rosered.cc-very-unique-value"
        exc = UnexpectedQueryProperties(
            [EventPropertyFilter(key="$entry_referring_domain", operator=PropertyOperator.EXACT, value=offending_value)]
        )
        assert offending_value not in str(exc)
        assert "event" in str(exc)
        assert "$entry_referring_domain" in str(exc)
