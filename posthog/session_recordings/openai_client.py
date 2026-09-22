"""OpenAI client for the replay AI regex endpoint.

Lifted out of the retired session-summaries package, which owned it only because that was the first
replay feature to call OpenAI directly.
"""

import os

from django.conf import settings

import posthoganalytics
from posthoganalytics.ai.openai import OpenAI
from posthoganalytics.client import Client
from rest_framework import exceptions

from posthog.cloud_utils import is_cloud

BASE_LLM_CALL_TIMEOUT_S = 600.0


def _get_default_posthog_client() -> Client:
    """Return the default analytics client after validating the environment."""
    if not settings.DEBUG and not is_cloud():
        raise exceptions.ValidationError("AI features are only available in PostHog Cloud")

    if not os.environ.get("OPENAI_API_KEY"):
        raise exceptions.ValidationError("OpenAI API key is not configured")

    client = posthoganalytics.default_client
    if not client:
        raise exceptions.ValidationError("PostHog analytics client is not configured")

    return client


def get_openai_client() -> OpenAI:
    """Get configured OpenAI client or raise appropriate error."""
    client = _get_default_posthog_client()
    return OpenAI(posthog_client=client, timeout=BASE_LLM_CALL_TIMEOUT_S, base_url=settings.OPENAI_BASE_URL)
