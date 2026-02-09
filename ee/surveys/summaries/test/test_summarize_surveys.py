from parameterized import parameterized

from ee.surveys.summaries.summarize_surveys import filter_low_signal_survey_responses, is_low_signal_survey_response


class TestSurveySummaryLowSignalFilter:
    @parameterized.expand(
        [
            ("empty", "", True),
            ("whitespace", "   \n\t", True),
            ("too_short", "ok", True),
            ("numbers", "12345", True),
            ("punctuation", "!!!", True),
            ("repeated_char", "aaaaaa", True),
            ("common_placeholder", "test", True),
            ("keyboard_mash_like", "ddsads", True),
            ("meaningful_single_word", "pricing", False),
            ("meaningful_two_words", "more integrations", False),
            ("meaningful_sentence", "Please add role-based access controls.", False),
        ]
    )
    def test_is_low_signal_survey_response(self, _name: str, response: str, expected: bool) -> None:
        assert is_low_signal_survey_response(response) is expected

    def test_filter_low_signal_survey_responses_returns_kept_and_dropped(self) -> None:
        kept, dropped = filter_low_signal_survey_responses(["ddsads", "more integrations", "test"])
        assert kept == ["more integrations"]
        assert dropped == ["ddsads", "test"]
