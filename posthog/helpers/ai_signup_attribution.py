"""Decide whether a signup that creates a new organization came through AI.

The result becomes organization group properties on PostHog's own analytics, so feature flags
and experiments can target organizations that AI sent to PostHog.
"""

import re
from enum import StrEnum

from posthog.dataclasses import frozen
from posthog.helpers.oauth_pending_connection import PendingOAuthConnection, PendingOAuthFlow
from posthog.models.channel_type.ai_sources import AI_SOURCES

AI_SIGNUP_SOURCE_PROPERTY = "ai_signup_source"
AI_SIGNUP_CLIENT_PROPERTY = "ai_signup_client"

# These lists mirror `AI_REFERRAL_PATTERNS` and `SOCIAL_REFERRAL_PATTERNS` in
# frontend/src/lib/components/SignupReferralSource.tsx, in the same order, so the server reaches
# the same verdict as the follow-up question the form shows. A parity test reads that file.
AI_REFERRAL_NAME_PATTERNS: tuple[str, ...] = (
    # AI labs
    "open ?ai",
    "anthropic",
    "perplexity",
    "x ?ai",
    "mistral",
    "eleven ?labs",
    "meta ?ai",
    "anysphere",
    "groq",
    "z.ai",
    # AI models and tooling
    "chat ?gpt",
    "gpt",
    "claude",
    "claud",
    "opus",
    "sonnet",
    "haiku",
    "gemini",
    "flash",
    "bard",
    "copilot",
    "deep ?seek",
    "grok",
    "qwen",
    "kimi",
    "devstral",
    "nemo",
    "composer",
    "codex",
    "cursor",
    "manus",
    "windsurf",
    "antigravity",
    "cline",
    "dia",
    # LLM coding platforms
    "repl ?it",
    "lovable",
    "hercules",
    "vercel",
    "v0",
    "bolt",
    "rork",
    "retool",
    "figma ?make",
    "poke",
    "clawdbot",
    "moltbot",
    "openclaw",
    "ai.com",
)
# Words that say AI was involved without naming a product, so they never become the client name.
AI_REFERRAL_GENERIC_PATTERNS: tuple[str, ...] = (
    "ai",
    "llm",
    "large language model",
    "artificial intelligence",
    "assistant",
    "chat",
    "vibe ?coding",
    "mcp",
    "ia",
    "ki",
)
AI_REFERRAL_PATTERNS: tuple[str, ...] = (*AI_REFERRAL_NAME_PATTERNS, *AI_REFERRAL_GENERIC_PATTERNS)

SOCIAL_REFERRAL_PATTERNS: tuple[str, ...] = (
    r"insta\w*",
    "ig",
    r"tik ?tok\w*",
    r"you ?tub\w*",
    "yt",
    "twitter",
    r"tweet\w*",
    "x",
    "x.com",
    "linked ?in",
    "facebook",
    "fb",
    "threads",
    "blue ?sky",
    "mastodon",
    r"reddit\w*",
    "twitch",
    r"snap ?chat\w*",
    "discord",
    "telegram",
    "whats ?app",
    "we ?chat",
    "weibo",
    "pinterest",
    "social ?media",
    r"social ?network\w*",
    r"influencer\w*",
    r"creator\w*",
    r"content ?creator\w*",
    r"streamer\w*",
    r"blogger\w*",
    r"vlogger\w*",
    r"podcast\w*",
    r"news ?letter\w*",
    "substack",
)

# "chat" also names social features ("Twitch chat"), so it does not decide for AI when a social
# trigger is present, as in the frontend tie-break.
_SOCIAL_AMBIGUOUS_AI_PATTERN = "chat"


def _word_pattern(patterns: tuple[str, ...]) -> re.Pattern[str]:
    # re.ASCII gives `\b` and `\w` the ASCII meaning they have in the frontend JavaScript regex.
    return re.compile(rf"\b({'|'.join(patterns)})\b", re.IGNORECASE | re.ASCII)


_AI_REFERRAL_RE = _word_pattern(AI_REFERRAL_PATTERNS)
_AI_REFERRAL_NAME_RE = _word_pattern(AI_REFERRAL_NAME_PATTERNS)
_AI_TIEBREAK_RE = _word_pattern(tuple(p for p in AI_REFERRAL_PATTERNS if p != _SOCIAL_AMBIGUOUS_AI_PATTERN))
_SOCIAL_REFERRAL_RE = _word_pattern(SOCIAL_REFERRAL_PATTERNS)

_AI_SOURCES = frozenset(AI_SOURCES)


class AISignupSource(StrEnum):
    CONNECTOR = "connector"
    DEVICE_LOGIN = "device_login"
    SAID_AI = "said_ai"
    AI_REFERRER = "ai_referrer"


@frozen
class AISignupAttribution:
    source: AISignupSource
    client: str | None = None

    def to_properties(self) -> dict[str, str]:
        properties = {AI_SIGNUP_SOURCE_PROPERTY: self.source.value}

        if self.client:
            properties[AI_SIGNUP_CLIENT_PROPERTY] = self.client

        return properties


def referral_source_says_ai(referral_source: str) -> bool:
    """Whether the signup form asks this answer the AI follow-up question."""
    if not _AI_REFERRAL_RE.search(referral_source):
        return False

    if _SOCIAL_REFERRAL_RE.search(referral_source):
        return _AI_TIEBREAK_RE.search(referral_source) is not None

    return True


def _named_ai(referral_source: str) -> str | None:
    match = _AI_REFERRAL_NAME_RE.search(referral_source)
    if match is None:
        return None

    # Drops the optional space the patterns allow, so "Chat GPT" and "ChatGPT" give one name.
    return re.sub(r"\s+", "", match.group(0).lower())


def _ai_referrer(initial_referring_domain: str, initial_utm_source: str) -> str | None:
    for candidate in (initial_referring_domain, initial_utm_source):
        normalized = candidate.strip().lower()
        if normalized in _AI_SOURCES:
            return normalized

    return None


def classify_ai_signup(
    *,
    oauth_connection: PendingOAuthConnection | None,
    referral_source: str,
    initial_referring_domain: str,
    initial_utm_source: str,
) -> AISignupAttribution | None:
    """The first AI signal that applies, from the strongest evidence to the weakest, or None."""
    if oauth_connection is not None:
        source = (
            AISignupSource.DEVICE_LOGIN
            if oauth_connection.flow == PendingOAuthFlow.DEVICE
            else AISignupSource.CONNECTOR
        )
        return AISignupAttribution(source=source, client=oauth_connection.client_name)

    if referral_source_says_ai(referral_source):
        return AISignupAttribution(source=AISignupSource.SAID_AI, client=_named_ai(referral_source))

    referrer = _ai_referrer(initial_referring_domain, initial_utm_source)
    if referrer is not None:
        return AISignupAttribution(source=AISignupSource.AI_REFERRER, client=referrer)

    return None
