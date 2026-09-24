"""Which OpenAI models may request the flex service tier, and which failures escalate off it."""

import re

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


# OpenAI answers a request whose body it could not read with a 400 that names the JSON body.
# We send the same body on both tiers, so that failure is in the transfer, not in the request,
# and the standard tier can still serve the window.
_JSON_BODY_PARSE_MESSAGE = re.compile(r"parse\s+(?:the\s+)?json\s+body", re.IGNORECASE)


def is_flex_recoverable(error: APIError) -> bool:
    """Whether a failed flex attempt should retry on the standard tier.

    Recoverable: a capacity refusal (429), a connection reset or client timeout
    (APIConnectionError covers its APITimeoutError subclass), any 5xx (the ai-gateway answers
    504 at its buffered-response ceiling), 408/409, which the SDK's own retry loop also
    retries and raises as the bare APIStatusError (OpenAI's flex docs use 408 for a
    server-side flex timeout), and a 400 that reports an unreadable request body. Every other
    400 and the auth errors are a configuration problem the standard tier shares, so they
    propagate instead of masking themselves behind a fallback.
    """
    if isinstance(error, RateLimitError | APIConnectionError | InternalServerError):
        return True
    if not isinstance(error, APIStatusError):
        return False
    if error.status_code in (408, 409):
        return True
    return error.status_code == 400 and bool(_JSON_BODY_PARSE_MESSAGE.search(str(error)))
