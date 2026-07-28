import os

from django.conf import settings

from posthog.cloud_utils import is_cloud

CLOUD_ONLY_MESSAGE = "Session summaries are only available in PostHog Cloud"
MISSING_API_KEY_MESSAGE = (
    "Session summaries need an OpenAI API key. Set OPENAI_API_KEY on your instance to enable them."
)


def session_summaries_environment_allowed() -> bool:
    """Whether this deployment is one where session summaries can run at all.

    A deployment fact rather than a transient failure: no retry turns a self-hosted
    instance into a cloud one, so dispatch paths should refuse work up front instead of
    fanning out per-session work that can only fail.
    """
    return bool(settings.DEBUG) or is_cloud()


def session_summaries_unavailable_reason() -> str | None:
    """None when a user can ask for a session summary here, otherwise a user-facing reason."""
    if not session_summaries_environment_allowed():
        return CLOUD_ONLY_MESSAGE
    if not os.environ.get("OPENAI_API_KEY"):
        return MISSING_API_KEY_MESSAGE
    return None
