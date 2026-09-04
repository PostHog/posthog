import re

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.scripts.hog_corpus_diagnostic import _REDACTION_PASSES as HOG_PASSES
from posthog.hogql.scripts.log_corpus_diagnostic import _REDACTION_PASSES as LOG_PASSES

_GITHUB_APP_ID = "1234567"
_JWT_BODY = ".".join(("a" * 169, "b" * 169, "c" * 169))

# A `ghs_` installation token carries its app id and a JWT, so `_` and `.` sit inside the
# token itself. GitHub varies the length, so the sample is shaped, not sized, like the real one.
STATELESS_INSTALLATION_TOKEN = f"ghs_{_GITHUB_APP_ID}_{_JWT_BODY}"

CREDENTIALS = [
    ("github_installation_stateless", STATELESS_INSTALLATION_TOKEN, "<gh_token>"),
    ("github_installation_legacy", "ghs_" + "A" * 36, "<gh_token>"),
    ("github_oauth", "gho_" + "B" * 36, "<gh_token>"),
    ("github_user_to_server", "ghu_" + "C" * 36, "<gh_token>"),
    ("github_refresh", "ghr_" + "D" * 36, "<gh_token>"),
    ("github_classic_pat", "ghp_" + "E" * 36, "<gh_token>"),
    ("github_fine_grained_pat", "github_pat_" + "F" * 22 + "_" + "G" * 59, "<gh_token>"),
    ("posthog_project_api_key", "phc_" + "H" * 43, "<ph_token>"),
    ("stripe_secret_key", "sk_live_" + "I" * 24, "<stripe_key>"),
    ("aws_access_key_id", "AKIA" + "J" * 16, "<aws_key>"),
    ("slack_bot_token", "xoxb-" + "1" * 13 + "-" + "K" * 24, "<slack_token>"),
]


def _to_python_dialect(pattern: str) -> str:
    # Postgres spells the word boundary `\y`; Python and re2 both spell it `\b`.
    return pattern.replace(r"\y", r"\b")


def _redact(passes: list[tuple[str, str]], text: str) -> str:
    for pattern, replacement in passes:
        text = re.sub(_to_python_dialect(pattern), replacement, text)
    return text


class TestCorpusRedaction(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{name}_{dump}", secret, placeholder, passes)
            for name, secret, placeholder in CREDENTIALS
            for dump, passes in (("log", LOG_PASSES), ("hog", HOG_PASSES))
        ]
    )
    def test_credential_is_redacted_out_of_the_dump(
        self, _name: str, secret: str, placeholder: str, passes: list[tuple[str, str]]
    ) -> None:
        redacted = _redact(passes, f"select * from events where key = '{secret}'")

        assert secret not in redacted
        assert placeholder in redacted

    @parameterized.expand([("log", LOG_PASSES), ("hog", HOG_PASSES)])
    def test_ordinary_query_text_survives_redaction(self, _name: str, passes: list[tuple[str, str]]) -> None:
        query = "select properties.gh_repo, person.properties.github_handle from events"

        assert _redact(passes, query) == query
