import pytest

from posthog.temporal.ai_observability.evaluation_workflow_activities import _evaluation_organization_id
from posthog.temporal.ai_observability.team_capture import clear_team_api_token_cache


@pytest.fixture(autouse=True)
def _clear_team_api_token_cache():
    # The token cache is per worker process, so it would otherwise leak across tests that
    # reuse team ids from a rolled-back transaction.
    clear_team_api_token_cache()
    _evaluation_organization_id.cache_clear()  # type: ignore[attr-defined] # cachetools stubs omit cache_clear
    yield
    clear_team_api_token_cache()
    _evaluation_organization_id.cache_clear()  # type: ignore[attr-defined] # cachetools stubs omit cache_clear
