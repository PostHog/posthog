import random
from datetime import UTC, datetime

from django.test import SimpleTestCase

from posthog.helpers.email_utils import _URL_SCHEME_RE, _url_scheme_matches, validate_message_body
from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.test.regex_timeout import assert_regex_completes

from products.logs.backend.log_patterns import LogSample, compile_match_regex, mine_patterns


class TestRemainingRegexBoundaries(SimpleTestCase):
    def test_json_log_surrogate_withholds_predicate(self) -> None:
        source = '{"message": "message \\ud800"}'
        sample = LogSample(source, "info", "test", datetime(2026, 9, 11, tzinfo=UTC))
        patterns = mine_patterns([sample])
        assert len(patterns) == 1
        assert patterns[0].match_regex is None

    def test_raw_log_surrogate_withholds_predicate(self) -> None:
        source = "message \ud800"
        sample = LogSample(source, "info", "test", datetime(2026, 9, 11, tzinfo=UTC))
        assert compile_match_regex("message <*>", [sample], [source]) is None

    def test_log_validation_uses_backend_whitespace_semantics(self):
        source = "message\u00a0value"
        sample = LogSample(source, "info", "test", datetime(2026, 9, 11, tzinfo=UTC))
        # Python's \s accepts NBSP, but ClickHouse/RE2's does not. Do not offer
        # a predicate that cannot match the example it was validated against.
        assert compile_match_regex("message <*>", [sample], [source]) is None

    def test_url_scheme_matching_compatibility(self):
        rng = random.Random(3)
        corpus = ["www.http://example.com", "123a://www.example.com", "İıſK://", "éjavascript:x", "www.www."]
        corpus += ["".join(rng.choices("abchttpswww./:0-İıſKé\n", k=50)) for _ in range(2_000)]
        for source in corpus:
            expected = [(match.span(), match.group()) for match in _URL_SCHEME_RE.finditer(source)]
            assert [(match.span(), match.group()) for match in _url_scheme_matches(source)] == expected, repr(source)

    def test_markdown_simple_links_preserve_unicode_and_nested_labels(self):
        assert (
            strip_external_links_markdown("![nested [label\ud800](https://example.com/image)") == "nested [label\ud800"
        )
        assert strip_external_links_markdown("<https://posthog.com/a\u00a0b>") == "<https://posthog.com/a\u00a0b>"

    def test_markdown_image_openers(self):
        def check():
            source = "![" * 100_000
            assert strip_external_links_markdown(source) == source

        assert_regex_completes(check)

    def test_markdown_unclosed_autolinks(self):
        def check():
            source = "<https://posthog.com/" * 20_000
            assert strip_external_links_markdown(source) == source

        assert_regex_completes(check)

    def test_log_template_validation(self):
        def check():
            source = "message " + "a" * 100 + "!"
            sample = LogSample(source, "info", "test", datetime(2026, 9, 11, tzinfo=UTC))
            assert compile_match_regex("message " + "<*>" * 20 + "end", [sample], [source]) is None

        assert_regex_completes(check)

    def test_message_without_url_scheme(self):
        def check():
            source = "a" * 100_000
            assert validate_message_body(source) == source

        assert_regex_completes(check)
