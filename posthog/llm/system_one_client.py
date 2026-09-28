"""Picks the System One server a caller reaches, the way ``build_openai_client`` picks a chat gateway.

The Go ai-gateway serves System One models that PostHog hosts, and bills the wallet of the team that
owns ``AI_GATEWAY_API_KEY``. TypeSafe serves Jev, but a caller reaches it only by passing a
``TypeSafeFallback``: TypeSafe is a third party, approved for experiments that send no customer data
(see ``posthog/egress/typesafe/README.md``). The two serve different models, so the fallback names
its own, and the result says which model answered.
"""

from collections.abc import Mapping
from dataclasses import field
from urllib.parse import urlparse, urlunparse

from django.conf import settings

import httpx
import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe.client import system_one
from posthog.llm.gateway_client import AIGatewayConfig, ai_gateway_headers, resolve_ai_gateway_config
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

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0

# The decision models the gateway serves (JevK5) answer with one letter per option, A to P.
GATEWAY_MAX_CHOICE_OPTIONS = 16
GATEWAY_MAX_QUESTIONS = 32


@frozen
class TypeSafeFallback:
    """Where no gateway is configured, ask TypeSafe for ``model`` from the ``source`` egress budget."""

    model: str
    source: str
    priority: Priority = Priority.NORMAL


@frozen
class GatewaySystemOneClient:
    url: str
    api_key: str = field(repr=False)
    headers: Mapping[str, str]
    model: str
    timeout: float

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        if not 1 <= len(questions) <= GATEWAY_MAX_QUESTIONS:
            raise ValueError(f"A System One request needs between 1 and {GATEWAY_MAX_QUESTIONS} questions")
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


def _usable_gateway() -> AIGatewayConfig | None:
    """The gateway config, unless its key would travel in clear to a host off this machine."""
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        return None
    parsed = urlparse(gateway.url)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        logger.warning("system_one_gateway_url_not_https")
        return None
    return gateway


def system_one_configured(typesafe_fallback: TypeSafeFallback | None = None) -> bool:
    if _usable_gateway() is not None:
        return True
    return typesafe_fallback is not None and bool(settings.TYPESAFE_API_KEY)


def build_system_one_client(
    *,
    model: str,
    ai_product: str,
    typesafe_fallback: TypeSafeFallback | None = None,
    distinct_id: str | None = None,
    trace_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> SystemOneClient:
    """A client for ``model`` on the Go ai-gateway when it is configured, else for TypeSafe when the
    caller passes ``typesafe_fallback``.

    ``ai_product``, ``distinct_id``, ``trace_id`` and ``properties`` label the gateway's event. Raises
    :class:`SystemOneNotConfigured` when no server the caller allows is configured.
    """
    gateway = _usable_gateway()
    if gateway is not None:
        return GatewaySystemOneClient(
            url=_system_one_url(gateway.url),
            api_key=gateway.api_key,
            headers=ai_gateway_headers(
                ai_product=ai_product, trace_id=trace_id, properties=properties, distinct_id=distinct_id
            )
            or {},
            model=model,
            timeout=timeout,
        )
    if typesafe_fallback is None:
        raise SystemOneNotConfigured("Configure AI_GATEWAY_URL (https) and AI_GATEWAY_API_KEY")
    if not settings.TYPESAFE_API_KEY:
        raise SystemOneNotConfigured("Configure AI_GATEWAY_URL and AI_GATEWAY_API_KEY, or TYPESAFE_API_KEY")
    return TypeSafeSystemOneClient(
        model=typesafe_fallback.model,
        source=typesafe_fallback.source,
        priority=typesafe_fallback.priority,
        timeout=timeout,
    )
