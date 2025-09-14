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
            # Core functionality - removing action verbs
            EvalCase(input="summarize sessions from yesterday", expected="sessions from yesterday"),
            EvalCase(input="analyze mobile user sessions from last week", expected="mobile sessions last week"),
            EvalCase(input="I want to understand what users did in checkout flow", expected="checkout flow sessions"),
            # Preserving key filtering criteria
            EvalCase(
                input="show me sessions longer than 5 minutes from Chrome users",
                expected="sessions longer than 5 minutes Chrome users",
            ),
            EvalCase(input="watch recordings of user ID 12345 from past week", expected="user ID 12345 past week"),
            # Complex queries should keep all conditions
            EvalCase(
                input="find iOS sessions from California with purchase events over $100",
                expected="iOS California purchase events over $100",
            ),
            # Edge cases
            EvalCase(input="summarize everything", expected="all sessions"),
            EvalCase(input="just the recent stuff", expected="recent sessions"),
        ],
        pytestconfig=pytestconfig,
    )
