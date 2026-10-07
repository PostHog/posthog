from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlsplit

import httpx

from posthog.llm.system_one import (
    JsonValue,
    NoulQuestion,
    Question,
    SystemOneRequestFailed,
    SystemOneResult,
    build_system_one_body,
    parse_system_one_response,
)
from posthog.models import Team
from posthog.ph_client import get_feature_flag_or_none
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import UNRESOLVED_HOST_REASON, has_authority_bypass_chars, validate_url_and_pin_ips

from products.ai_observability.backend.llm.errors import (
    RESPONSE_LIMIT_MESSAGE,
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ModelNotFoundError,
    ModelPermissionError,
    ProviderConnectionError,
    ProviderHostUnresolvedError,
    ProviderRequestRejectedError,
    QuotaExceededError,
    RateLimitError,
    RetryableRateLimitError,
    StructuredOutputParseError,
    is_context_window_error_message,
)
from products.ai_observability.backend.llm.providers._diagnostics import tagged_http_client
from products.ai_observability.backend.llm.providers.openrouter import OPENROUTER_HEADERS, decision_model_ids


def is_decision_model(provider: str | None, model: str | None, *, openrouter_enabled: bool) -> bool:
    if provider == "system_one":
        return True
    # Disabled projects keep the chat path independent of catalogue availability.
    if provider != "openrouter" or not model or not openrouter_enabled:
        return False
    models = decision_model_ids()
    if models is None:
        raise ProviderConnectionError("Could not load OpenRouter model capabilities. Try again.")
    return model in models


def decision_evaluations_enabled(team_id: int, *, base_url: str) -> bool:
    try:
        host = (urlsplit(base_url).hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
    except (ValueError, UnicodeError):
        return False
    if not host or host == "typesafe.ai" or host.endswith(".typesafe.ai"):
        return False
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    return (
        get_feature_flag_or_none(
            "llm-analytics-system-one-evaluations",
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            send_feature_flag_events=False,
        )
        is True
    )


class DecisionRequestRejectedError(ProviderRequestRejectedError):
    pass


class DecisionEndpointBlockedError(LLMError):
    pass


class DecisionRateLimitError(RetryableRateLimitError):
    def __init__(self, retry_after: str | None) -> None:
        super().__init__("The decision endpoint is temporarily unavailable. Try again later.", retry_after)


class DecisionClient:
    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        parsed = urlsplit(base_url)
        if (
            has_authority_bypass_chars(base_url)
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTPS base URL without credentials, a query, or a fragment.")
        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as error:
            raise ValueError("Use a valid HTTPS hostname.") from error
        if host == "typesafe.ai" or host.endswith(".typesafe.ai"):
            raise ValueError("This hosted endpoint is not available for evaluations.")
        return base_url.rstrip("/")

    @staticmethod
    def evaluate(
        *,
        api_key: str,
        model: str,
        state: JsonValue,
        questions: Mapping[str, Question],
        base_url: str,
        timeout: float = 60,
        path: Literal["systemone", "decisions"] = "systemone",
    ) -> SystemOneResult:
        try:
            base_url = DecisionClient.normalize_base_url(base_url)
        except ValueError as error:
            raise DecisionEndpointBlockedError(str(error)) from error
        try:
            verdict = validate_url_and_pin_ips(base_url)
            if not verdict.allowed:
                if verdict.reason == UNRESOLVED_HOST_REASON:
                    raise ProviderHostUnresolvedError()
                raise SSRFBlockedError(verdict.reason)
            headers = dict(OPENROUTER_HEADERS) if path == "decisions" else {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            with tagged_http_client(
                pin=(base_url, verdict.pinned_ips),
                timeout=timeout,
                total_timeout=timeout,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{base_url}/{path}",
                    headers=headers,
                    json=build_system_one_body(state=state, questions=questions, model=model),
                )
        except SSRFBlockedError as error:
            raise DecisionEndpointBlockedError("This endpoint is not allowed. Use a public HTTPS endpoint.") from error
        except httpx.DecodingError as error:
            raise DecisionRequestRejectedError(RESPONSE_LIMIT_MESSAGE) from error
        except httpx.RequestError as error:
            raise ProviderConnectionError("Could not reach the decision endpoint. Try again.") from error

        status = response.status_code
        if status == 200:
            try:
                return parse_system_one_response(response.json(), questions)
            except (ValueError, SystemOneRequestFailed) as error:
                raise StructuredOutputParseError(
                    "The endpoint returned an invalid decision response. Check compatibility."
                ) from error
        if status == 401:
            raise AuthenticationError("The endpoint rejected this credential. Check the bearer token.")
        if status == 402:
            raise QuotaExceededError("The endpoint account has insufficient credits. Check its billing settings.")
        if status == 403:
            raise ModelPermissionError(model)
        if status == 404:
            raise ModelNotFoundError(model)
        if status in (408, 429, 503, 529):
            raise DecisionRateLimitError(response.headers.get("Retry-After"))
        if status >= 500:
            raise ProviderConnectionError("The decision endpoint is temporarily unavailable. Try again.")
        if 300 <= status < 400:
            # OpenRouter owns this fixed endpoint; redirects must not invalidate its shared key.
            if path == "decisions":
                raise ProviderConnectionError("The OpenRouter decision endpoint redirected the request. Try again.")
            raise DecisionEndpointBlockedError("The endpoint redirected the request. Use its final HTTPS URL.")
        if status == 413 or (status == 422 and is_context_window_error_message(response.text)):
            raise ContextWindowExceededError("This input exceeds the endpoint's size limit. Reduce the input.")
        raise DecisionRequestRejectedError(
            "The endpoint rejected the evaluation request. "
            "Check that the model supports this evaluation's output type and criteria."
        )

    @staticmethod
    def validate_key(api_key: str, *, base_url: str, model: str) -> tuple[str, str | None]:
        try:
            DecisionClient.evaluate(
                api_key=api_key,
                base_url=base_url,
                model=model,
                state="Hello!",
                timeout=10,
                questions={"verdict": NoulQuestion(instructions="Does the text contain a greeting?")},
            )
        except (AuthenticationError, ModelPermissionError) as error:
            return "invalid", str(error)
        except (
            ValueError,
            ModelNotFoundError,
            ProviderConnectionError,
            QuotaExceededError,
            RateLimitError,
            StructuredOutputParseError,
            DecisionEndpointBlockedError,
            DecisionRequestRejectedError,
            ContextWindowExceededError,
        ) as error:
            return "error", str(error)
        return "ok", None
