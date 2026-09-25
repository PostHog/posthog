"""Picks the System One server a caller reaches, the way ``build_openai_client`` picks a chat gateway.

The Go ai-gateway serves System One models that PostHog hosts, and bills the wallet of the team that
owns ``AI_GATEWAY_API_KEY``. TypeSafe serves Jev and is the fallback where no gateway is configured.
The two serve different models, so a caller names one model for each, and the result says which
model answered.
"""

from collections.abc import Mapping
from dataclasses import field
from urllib.parse import urlparse, urlunparse

from django.conf import settings

import httpx

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe.client import system_one
from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config
from posthog.llm.system_one import (
    SYSTEM_ONE_PATH,
    ChoiceQuestion,
    JsonValue,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
    build_system_one_body,
    parse_system_one_response,
)

# A decision takes milliseconds, and the gateway gives up on a silent host within seconds.
DEFAULT_TIMEOUT_SECONDS = 5.0

# The decision models the gateway serves (JevK5) answer with one letter per option, A to P.
GATEWAY_MAX_CHOICE_OPTIONS = 16


@frozen
class SystemOneModels:
    gateway: str
    typesafe: str


@frozen
class GatewaySystemOneClient:
    url: str
    api_key: str = field(repr=False)
    headers: Mapping[str, str]
    model: str
    timeout: float

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        if not questions:
            raise ValueError("A System One request needs at least one question")
        for question_id, question in questions.items():
            if isinstance(question, ChoiceQuestion) and len(question.criteria) > GATEWAY_MAX_CHOICE_OPTIONS:
                raise ValueError(f"{question_id!r} has more than {GATEWAY_MAX_CHOICE_OPTIONS} options")
        try:
            with httpx.Client(trust_env=False, timeout=self.timeout) as client:
                response = client.post(
                    self.url,
                    json=build_system_one_body(state=state, questions=questions, model=self.model),
                    headers={**self.headers, "Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as exc:
            raise SystemOneRequestFailed(f"The ai-gateway was not reached: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            # The error body can echo the state, so it stays out of the exception that gets logged.
            raise SystemOneRequestFailed(
                f"The ai-gateway returned HTTP {response.status_code}", status_code=response.status_code
            )
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise SystemOneRequestFailed("The ai-gateway returned a non-JSON body") from exc
        return parse_system_one_response(payload, questions)


@frozen
class TypeSafeSystemOneClient:
    model: str
    source: str
    priority: Priority
    timeout: float

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        return system_one(
            state=state,
            questions=questions,
            source=self.source,
            model=self.model,
            priority=self.priority,
            timeout=self.timeout,
        )


type SystemOneClient = GatewaySystemOneClient | TypeSafeSystemOneClient


def _system_one_url(gateway_url: str) -> str:
    """The gateway URL setting carries the OpenAI ``/v1`` base path, and System One hangs off the origin."""
    parsed = urlparse(gateway_url)
    path = parsed.path.rstrip("/").removesuffix("/v1")
    return urlunparse(parsed._replace(path=path + SYSTEM_ONE_PATH, params="", query="", fragment=""))


def _carries_credentials_safely(gateway_url: str) -> bool:
    parsed = urlparse(gateway_url)
    return parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def system_one_configured() -> bool:
    return resolve_ai_gateway_config() is not None or bool(settings.TYPESAFE_API_KEY)


def build_system_one_client(
    *,
    models: SystemOneModels,
    ai_product: str,
    typesafe_source: str,
    priority: Priority = Priority.NORMAL,
    distinct_id: str | None = None,
    trace_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> SystemOneClient:
    """A client for the Go ai-gateway when it is configured, else for TypeSafe.

    ``ai_product``, ``distinct_id``, ``trace_id`` and ``properties`` label the gateway's event.
    ``typesafe_source`` and ``priority`` pick TypeSafe's egress budget lane. Raises
    :class:`SystemOneNotConfigured` when neither server is configured.
    """
    gateway = resolve_ai_gateway_config()
    if gateway is not None:
        if not _carries_credentials_safely(gateway.url):
            raise SystemOneNotConfigured("AI_GATEWAY_URL must use https unless it points at this machine")
        return GatewaySystemOneClient(
            url=_system_one_url(gateway.url),
            api_key=gateway.api_key,
            headers=ai_gateway_headers(
                ai_product=ai_product, trace_id=trace_id, properties=properties, distinct_id=distinct_id
            )
            or {},
            model=models.gateway,
            timeout=timeout,
        )
    if settings.TYPESAFE_API_KEY:
        return TypeSafeSystemOneClient(
            model=models.typesafe, source=typesafe_source, priority=priority, timeout=timeout
        )
    raise SystemOneNotConfigured("Configure AI_GATEWAY_URL and AI_GATEWAY_API_KEY, or TYPESAFE_API_KEY")
