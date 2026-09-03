import pytest

from posthog.temporal.ai_observability.team_capture import clear_team_api_token_cache


@pytest.fixture(autouse=True)
def _clear_team_api_token_cache():
    # The token cache is per worker process, so it would otherwise leak across tests that
    # reuse team ids from a rolled-back transaction.
    clear_team_api_token_cache()
    yield
    clear_team_api_token_cache()
