import re
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.helpers.ai_signup_attribution import (
    AI_REFERRAL_PATTERNS,
    SOCIAL_REFERRAL_PATTERNS,
    AISignupAttribution,
    AISignupSource,
    classify_ai_signup,
)
from posthog.helpers.oauth_pending_connection import PendingOAuthConnection, PendingOAuthFlow

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_REFERRAL_SOURCE_FILE = REPO_ROOT / "frontend/src/lib/components/SignupReferralSource.tsx"

CLIENT_NAME = "Claude"
CLIENT_ID = "https://claude.example.com/.well-known/oauth-client"
AI_REFERRING_DOMAIN = "chatgpt.com"
NON_AI_REFERRING_DOMAIN = "www.google.com"
DIRECT_REFERRING_DOMAIN = "$direct"


def _connection(flow: PendingOAuthFlow) -> PendingOAuthConnection:
    return PendingOAuthConnection(client_name=CLIENT_NAME, client_id=CLIENT_ID, flow=flow)


def _frontend_string_array(source: str, name: str) -> list[str]:
    match = re.search(rf"const {name} = \[(.*?)\n\]", source, re.DOTALL)
    assert match is not None, f"{name} not found in {FRONTEND_REFERRAL_SOURCE_FILE}"

    without_comments = re.sub(r"//[^\n]*", "", match.group(1))
    literals = re.findall(r"'((?:[^'\\]|\\.)*)'", without_comments)

    return [literal.replace("\\\\", "\\") for literal in literals]


class TestClassifyAISignup(SimpleTestCase):
    @parameterized.expand(
        [
            ("connector", PendingOAuthFlow.AUTHORIZE, "", "", "", AISignupSource.CONNECTOR, CLIENT_NAME),
            ("device_login", PendingOAuthFlow.DEVICE, "", "", "", AISignupSource.DEVICE_LOGIN, CLIENT_NAME),
            ("said_named_ai", None, "ChatGPT recommended it", "", "", AISignupSource.SAID_AI, "chatgpt"),
            ("said_named_ai_with_space", None, "I asked Chat GPT", "", "", AISignupSource.SAID_AI, "chatgpt"),
            ("said_generic_ai", None, "an AI assistant", "", "", AISignupSource.SAID_AI, None),
            ("said_ai_beats_social_mention", None, "Claude on YouTube", "", "", AISignupSource.SAID_AI, "claude"),
            ("ai_referring_domain", None, "", AI_REFERRING_DOMAIN, "", AISignupSource.AI_REFERRER, "chatgpt.com"),
            ("ai_utm_source", None, "", DIRECT_REFERRING_DOMAIN, "Claude", AISignupSource.AI_REFERRER, "claude"),
            (
                "connector_beats_said_ai_and_referrer",
                PendingOAuthFlow.AUTHORIZE,
                CLIENT_NAME,
                AI_REFERRING_DOMAIN,
                "",
                AISignupSource.CONNECTOR,
                CLIENT_NAME,
            ),
            (
                "said_ai_beats_referrer",
                None,
                "Perplexity",
                AI_REFERRING_DOMAIN,
                "",
                AISignupSource.SAID_AI,
                "perplexity",
            ),
        ]
    )
    def test_attributes_the_first_ai_signal(
        self,
        _name: str,
        flow: PendingOAuthFlow | None,
        referral_source: str,
        initial_referring_domain: str,
        initial_utm_source: str,
        expected_source: AISignupSource,
        expected_client: str | None,
    ) -> None:
        attribution = classify_ai_signup(
            oauth_connection=_connection(flow) if flow is not None else None,
            referral_source=referral_source,
            initial_referring_domain=initial_referring_domain,
            initial_utm_source=initial_utm_source,
        )

        assert attribution == AISignupAttribution(source=expected_source, client=expected_client)

    @parameterized.expand(
        [
            ("no_signal", "", "", ""),
            ("non_ai_answer", "a colleague told me", "", ""),
            ("social_chat_is_not_ai", "Twitch chat", "", ""),
            ("ai_inside_another_word", "found you while waiting for a train", "", ""),
            ("non_ai_referrer", "", NON_AI_REFERRING_DOMAIN, "newsletter"),
            ("direct_visit", "", DIRECT_REFERRING_DOMAIN, ""),
        ]
    )
    def test_returns_nothing_without_an_ai_signal(
        self, _name: str, referral_source: str, initial_referring_domain: str, initial_utm_source: str
    ) -> None:
        attribution = classify_ai_signup(
            oauth_connection=None,
            referral_source=referral_source,
            initial_referring_domain=initial_referring_domain,
            initial_utm_source=initial_utm_source,
        )

        assert attribution is None

    @parameterized.expand(
        [
            ("ai", "AI_REFERRAL_PATTERNS", AI_REFERRAL_PATTERNS),
            ("social", "SOCIAL_REFERRAL_PATTERNS", SOCIAL_REFERRAL_PATTERNS),
        ]
    )
    def test_patterns_match_the_signup_form(self, _name: str, frontend_name: str, patterns: tuple[str, ...]) -> None:
        source = FRONTEND_REFERRAL_SOURCE_FILE.read_text()

        frontend_patterns = _frontend_string_array(source, frontend_name)

        assert frontend_patterns == list(patterns)
