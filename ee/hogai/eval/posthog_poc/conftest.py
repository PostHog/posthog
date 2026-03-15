from __future__ import annotations

import os

import pytest

from posthog.conftest import _django_db_setup

from .client import PostHogEvalClient

pytest_plugins = (
    "ee.hogai.eval.posthog_poc.suites.ticket_summary",
    "ee.hogai.eval.posthog_poc.suites.memory",
)


@pytest.fixture(scope="session")
def set_up_evals(django_db_setup, django_db_keepdb, django_db_blocker):  # noqa: F811
    yield from _django_db_setup(django_db_keepdb, django_db_blocker)


@pytest.fixture
def posthog_eval_client() -> PostHogEvalClient:
    if not os.getenv("POSTHOG_EVALS_HOST") or not os.getenv("POSTHOG_EVALS_PROJECT_API_KEY"):
        pytest.skip("PostHog eval POC secrets are not configured")

    client = PostHogEvalClient.from_env()
    try:
        yield client
    finally:
        client.shutdown()
