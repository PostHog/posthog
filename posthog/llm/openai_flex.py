"""Which OpenAI models may request the flex service tier, and which failures escalate off it."""

from openai import APIConnectionError, APIError, APIStatusError, BadRequestError, InternalServerError, RateLimitError

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

# A 400 with this wording points at a request body damaged in transit, not a bad request,
# so a second send on the standard tier can succeed.
_UNREADABLE_REQUEST_PHRASE = "reading your request"


def is_flex_recoverable(error: APIError) -> bool:
    """Whether a failed flex attempt should retry on the standard tier.

    Recoverable: a capacity refusal (429), a connection reset or client timeout
    (APIConnectionError covers its APITimeoutError subclass), any 5xx (the ai-gateway answers
    504 at its buffered-response ceiling), and 408/409, which the SDK's own retry loop also
    retries and raises as the bare APIStatusError (OpenAI's flex docs use 408 for a
    server-side flex timeout), and a 400 that says the provider could not read the request.
    Anything else (other 400s, auth errors) is a configuration problem the standard tier
    shares, so it propagates instead of masking itself behind a fallback.
    """
    if isinstance(error, RateLimitError | APIConnectionError | InternalServerError):
        return True
    if isinstance(error, BadRequestError):
        return _UNREADABLE_REQUEST_PHRASE in error.message.lower()
    return isinstance(error, APIStatusError) and error.status_code in (408, 409)
