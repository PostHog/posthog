import re

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.scripts.hog_corpus_diagnostic import _REDACTION_PASSES as HOG_PASSES
from posthog.hogql.scripts.log_corpus_diagnostic import _REDACTION_PASSES as LOG_PASSES

STATELESS_INSTALLATION_TOKEN = "ghs_1234567_header-with-hyphen.payload_with_underscore.signature-with-hyphen"


def _to_python_dialect(pattern: str) -> str:
    # Postgres spells the word boundary `\y`; Python and re2 both spell it `\b`.
    return pattern.replace(r"\y", r"\b")


def _redact(passes: list[tuple[str, str]], text: str) -> str:
    for pattern, replacement in passes:
        text = re.sub(_to_python_dialect(pattern), replacement, text)
    return text


class TestCorpusRedaction(SimpleTestCase):
    @parameterized.expand([("log", LOG_PASSES), ("hog", HOG_PASSES)])
    def test_stateless_github_token_is_redacted(self, _name: str, passes: list[tuple[str, str]]) -> None:
        redacted = _redact(passes, f"select '{STATELESS_INSTALLATION_TOKEN}'")

        assert STATELESS_INSTALLATION_TOKEN not in redacted
        assert "<gh_token>" in redacted
