import pytest
from unittest.mock import MagicMock

from braintrust import EvalCase
from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.session_summaries.nodes import _SessionSearch

from ..base import MaxPublicEval
from ..scorers import SemanticSimilarity


@pytest.fixture
def filter_query_tester(demo_org_team_user):
    """Simple fixture to test filter query generation."""

    async def test(input_query: str) -> str:
        # Minimal mock setup
        mock_node = MagicMock()
        mock_node._team = demo_org_team_user[1]
        mock_node._user = demo_org_team_user[2]
        search = _SessionSearch(mock_node)
        return await search._generate_filter_query(input_query, RunnableConfig())

    return test


@pytest.mark.django_db
async def eval_filter_query_generation(filter_query_tester, pytestconfig):
    """Test that filter query generation preserves search intent while removing fluff."""

    await MaxPublicEval(
        experiment_name="filter_query_generation",
        task=filter_query_tester,
        scores=[SemanticSimilarity()],
        data=[
            EvalCase(input="summarize sessions from yesterday", expected="sessions from yesterday"),
            EvalCase(input="analyze mobile user sessions from last week", expected="mobile user sessions last week"),
            EvalCase(
                input="watch last 100 sessions, I want to understand what users did in checkout flow",
                expected="last 100 sessions",
            ),
            EvalCase(
                input="hey Max,show me sessions longer than 5 minutes from Chrome users",
                expected="sessions longer than 5 minutes fromChrome users",
            ),
            EvalCase(
                input="watch recordings of user ID 12345 from past week, I want to see the UX issues they are facing",
                expected="recordings of user ID 12345 from past week",
            ),
            EvalCase(
                input="summarize iOS sessions from California with purchase events over $100, do we have a lot of these?",
                expected="iOS sessions from California with purchase events over $100",
            ),
            EvalCase(
                input="Max, I need you to watch replays of German desktop Linux users from 21.03.2024 till 24.03.2024, and tell me what problems did they encounter",
                expected="replays of German desktop Linux users from 21.03.2024 till 24.03.2024",
            ),
        ],
        pytestconfig=pytestconfig,
    )
