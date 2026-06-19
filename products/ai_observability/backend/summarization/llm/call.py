"""
LLM calling function for summarization via LLM gateway.

Routes all summarization requests through the LLM gateway with OpenAI models.
"""

from typing import cast

from ..constants import DEFAULT_MODE, DEFAULT_MODEL_OPENAI
from ..models import OpenAIModel, SummarizationMode
from .openai import summarize_with_openai
from .schema import SummarizationResponse


def summarize(
    text_repr: str,
    team_id: int,
    mode: SummarizationMode = DEFAULT_MODE,
    model: OpenAIModel | None = None,
    user_id: str | None = None,
) -> SummarizationResponse:
    """
    Generate AI-powered summary from text representation via LLM gateway.

    Args:
        text_repr: Line-numbered text representation to summarize
        team_id: Team ID for cost tracking and analytics
        mode: Summary detail level
        model: OpenAI model to use (defaults to gpt-4.1-mini)
        user_id: Optional user distinct_id for analytics attribution

    Returns:
        Structured summarization response with flow diagram, bullets, and notes
    """
    openai_model = cast(OpenAIModel, model) if model else DEFAULT_MODEL_OPENAI
    return summarize_with_openai(text_repr, team_id, mode, openai_model, user_id)
