"""Size limits for the text representation handed to a summarization model."""

from ..text_repr.formatters import reduce_by_uniform_sampling
from .constants import DEFAULT_MODEL_OPENAI
from .models import OpenAIModel

# Input context window per model, in tokens. A model missing from here takes the smallest window,
# so an unrecognized `model` on a request cannot buy itself a budget the provider will not accept.
MODEL_CONTEXT_TOKENS: dict[str, int] = {
    OpenAIModel.GPT_4_1_NANO: 1_047_576,
    OpenAIModel.GPT_4_1_MINI: 1_047_576,
    OpenAIModel.GPT_4O_MINI: 128_000,
    OpenAIModel.GPT_4O: 128_000,
    OpenAIModel.GPT_5_MINI: 400_000,
}

# Held back from the window for the system prompt and the model's own response.
RESERVED_TOKENS = 20_000


def text_repr_budget(model: str | None = None) -> int:
    """Characters of text representation the model accepts.

    Spends one character per token, which is far more pessimistic than the ~1.6 that line-numbered
    trace text actually costs. The margin is deliberate: the ratio worsens with non-ASCII content
    and base64, and overshooting the window fails the request outright rather than degrading.
    """
    window = MODEL_CONTEXT_TOKENS.get(model or DEFAULT_MODEL_OPENAI, min(MODEL_CONTEXT_TOKENS.values()))
    return window - RESERVED_TOKENS


def bounded_text_repr(text: str, budget: int) -> str:
    """Reduce `text` to `budget` characters, sampling whole lines where it can."""
    if len(text) <= budget:
        return text
    bounded, _ = reduce_by_uniform_sampling(text, budget)
    return bounded
