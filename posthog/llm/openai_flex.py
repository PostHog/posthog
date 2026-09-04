"""Which OpenAI models may request the flex service tier, and which failures escalate off it."""

from openai import APIConnectionError, APIError, APIStatusError, InternalServerError, RateLimitError

# OpenAI decides flex eligibility per model, and the pro tiers are excluded, so callers must
# check membership here rather than infer it from a model family prefix. This mirrors the flex
# table on https://developers.openai.com/api/docs/pricing?latest-pricing=flex (September 2026);
# a new model joins only after someone checks that page.
FLEX_CAPABLE_MODELS: frozenset[str] = frozenset(
    {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "o3",
        "o4-mini",
    }
)


def is_flex_recoverable(error: APIError) -> bool:
    """Whether a failed flex attempt should retry on the standard tier.

    Recoverable: a capacity refusal (429), a connection reset or client timeout
    (APIConnectionError covers its APITimeoutError subclass), any 5xx (the ai-gateway answers
    504 at its buffered-response ceiling), and 408, which OpenAI's flex docs use for a
    server-side flex timeout and the SDK raises as the bare APIStatusError. Anything else
    (400 bad request, auth errors) is a configuration problem the standard tier shares, so it
    propagates instead of masking itself behind a fallback.
    """
    if isinstance(error, RateLimitError | APIConnectionError | InternalServerError):
        return True
    return isinstance(error, APIStatusError) and error.status_code == 408
