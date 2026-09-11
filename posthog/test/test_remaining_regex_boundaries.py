import re
import html
import random
import unicodedata
from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.helpers.email_utils import (
    _URL_SCHEME_RE,
    _bare_domain_spans,
    _url_scheme_matches,
    contains_bare_domain,
    sanitize_email_string,
    validate_message_body,
)
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

    @parameterized.expand([("1", False), ("com", True)])
    def test_bare_domain_long_label_chain(self, suffix: str, contains_domain: bool) -> None:
        def check() -> None:
            source = "a." * 20_000 + suffix
            assert contains_bare_domain(source) is contains_domain
            expected = "a.\u200b" * 20_000 + "com" if contains_domain else source
            assert sanitize_email_string(source) == expected

        assert_regex_completes(check)

    def test_bare_domain_matching_compatibility(self) -> None:
        baseline = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b", re.IGNORECASE)
        invisibles = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
        rng = random.Random(6)
        labels = ["a", "ab", "1", "a-b", "ab-", "-ab", "a" * 63, "a" * 64, "b" * 24, "b" * 25, "İıſK", "é", "_"]
        corpus = ["".join(rng.choices("aAbB01.-_éİıſK\ud800\udfff\u200b \n", k=60)) for _ in range(1_000)]
        corpus += [".".join(rng.choices(labels, k=rng.randrange(1, 9))) for _ in range(1_000)]
        corpus += ["ａ．ｃｏｍ", "a\u200b.com", "https://a.ab-cd.ef", "a.ab-.cd.ef", "<a.com>&b.com", "www.a.ab.cd"]

        def defang(match: re.Match[str]) -> str:
            return match.group().replace(".", ".\u200b").replace(":", ":\u200b")

        for source in corpus:
            expected_spans = [match.span() for match in baseline.finditer(source)]
            assert [(span.start, span.end) for span in _bare_domain_spans(source)] == expected_spans, repr(source)
            normalized = unicodedata.normalize("NFKC", source)
            assert contains_bare_domain(source) == bool(baseline.search(normalized)), repr(source)
            escaped = html.escape(invisibles.sub("", normalized))
            expected = baseline.sub(defang, _URL_SCHEME_RE.sub(defang, escaped))
            assert sanitize_email_string(source) == expected, repr(source)
