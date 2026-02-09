from parameterized import parameterized

from posthog.helpers.survey_response_quality import filter_survey_responses, should_ignore_survey_response


@parameterized.expand(
    [
        ("empty", "", True),
        ("whitespace", "   \n\t  ", True),
        ("punctuation_only", "....", True),
        ("placeholder_test", "test", True),
        ("placeholder_asdf", "asdfasdf", True),
        ("placeholder_qwerty", "qwerty", True),
        ("numbers_placeholder", "1234", True),
        ("repeated_characters", "aaaaaaaaaa", True),
        ("keyboard_smash_like", "hjdashdjksahd", True),
        ("meaningful_sentence", "The UI is slow when loading dashboards", False),
        ("meaningful_short", "none", False),
        ("meaningful_non_ascii", "przestrzeń", False),
        ("meaningful_japanese", "こんにちは", False),
    ]
)
def test_should_ignore_survey_response(_name: str, value: str, expected: bool) -> None:
    assert should_ignore_survey_response(value) is expected


def test_filter_survey_responses_filters_only_low_signal() -> None:
    responses = [
        "test",
        "hjdashdjksahd",
        "Dashboards load slowly on large projects",
        "none",
    ]

    assert filter_survey_responses(responses) == ["Dashboards load slowly on large projects", "none"]
