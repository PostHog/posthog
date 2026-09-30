"""Typed client for TypeSafe's System One endpoint, ``POST /v1/systemone``.

The request and answer types live in ``posthog.llm.system_one``, because the Go ai-gateway serves
the same API. This module adds TypeSafe's host, key, and egress budget.

USAGE POLICY. TypeSafe is approved for experiments only. Read "Usage policy" in this package's
README.md before you add a caller. In short: gate every caller behind a feature flag that reaches
PostHog staff only, and send no customer data. A launch that sends customer data needs an explicit
opt-in from each customer and sign-off from leadership first.
"""

from collections.abc import Mapping

from django.conf import settings

from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe.transport import DEFAULT_TIMEOUT, typesafe_request
from posthog.llm.system_one import (
    SYSTEM_ONE_PATH,
    JsonValue,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
    build_system_one_body,
    parse_system_one_response,
)

TYPESAFE_API_BASE = "https://api.typesafe.ai"
SYSTEM_ONE_ENDPOINT = SYSTEM_ONE_PATH

# The alias moves to each new release. A caller that tunes thresholds against one version pins that
# version's id instead, so a release cannot shift its answers without a code change.
JEV_LATEST = "jev-latest"


class TypeSafeNotConfigured(SystemOneNotConfigured):
    """No TypeSafe API key is configured on this instance, so no call was made."""


class TypeSafeRequestFailed(SystemOneRequestFailed):
    """TypeSafe was reached but did not return a usable answer."""


def system_one(
    *,
    state: JsonValue,
    questions: Mapping[str, Question],
    source: str,
    model: str = JEV_LATEST,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
) -> SystemOneResult:
    """Evaluate ``state`` against every question in one call. TypeSafe answers the questions in
    parallel, so a caller asks everything it needs in one request.

    Raises :class:`TypeSafeNotConfigured` when the instance has no API key,
    :class:`TypeSafeRequestFailed` when TypeSafe answers with anything but a complete set of answers,
    and :class:`~posthog.egress.typesafe.transport.TypeSafeEgressBudgetExhausted` when our own egress
    budget sheds the call. Nothing retries a 429 or a 529 here, so the caller owns any retry.
    """
    if not questions:
        raise ValueError("system_one needs at least one question")
    api_key = settings.TYPESAFE_API_KEY
    if not api_key:
        raise TypeSafeNotConfigured("No TYPESAFE_API_KEY configured")

    response = typesafe_request(
        "POST",
        f"{TYPESAFE_API_BASE}{SYSTEM_ONE_ENDPOINT}",
        api_key=api_key,
        source=source,
        endpoint=SYSTEM_ONE_ENDPOINT,
        priority=priority,
        timeout=timeout,
        allow_redirects=False,
        json=build_system_one_body(state=state, questions=questions, model=model),
    )

    if not response.ok:
        # A 422 body echoes the offending field, which can carry the state, so keep the body out of
        # the exception that gets logged.
        raise TypeSafeRequestFailed(f"TypeSafe returned HTTP {response.status_code}", status_code=response.status_code)
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise TypeSafeRequestFailed("TypeSafe returned a non-JSON body") from exc
    try:
        return parse_system_one_response(payload, questions)
    except SystemOneRequestFailed as exc:
        raise TypeSafeRequestFailed(str(exc)) from exc
