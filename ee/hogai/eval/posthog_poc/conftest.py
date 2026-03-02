from __future__ import annotations

import os

import pytest

from ee.hogai.eval.conftest import set_up_evals  # noqa: F401

from .client import PostHogEvalClient

pytest_plugins = ("posthog.conftest",)


@pytest.fixture
def posthog_eval_client() -> PostHogEvalClient:
    if not os.getenv("POSTHOG_EVALS_HOST") or not os.getenv("POSTHOG_EVALS_PROJECT_API_KEY"):
        pytest.skip("PostHog eval POC secrets are not configured")

    client = PostHogEvalClient.from_env()
    try:
        yield client
    finally:
        client.shutdown()
