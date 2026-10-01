import math
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from django.conf import settings

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
from posthog.security.pinned_httpx import pinned_client
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import has_authority_bypass_chars, validate_url_and_pin_ips

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ModelNotFoundError,
    ModelPermissionError,
    ProviderConnectionError,
    RateLimitError,
    StructuredOutputParseError,
    is_context_window_error_message,
)
from products.ai_observability.backend.llm.providers._diagnostics import _tag_response


def system_one_evaluations_enabled(team_id: int, *, base_url: str) -> bool:
    try:
        host = (urlsplit(base_url).hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
    except (ValueError, UnicodeError):
        return False
    if not host or host == "typesafe.ai" or host.endswith(".typesafe.ai"):
        return False
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    # Customer connections use their own provider account or deployment, never PostHog's gateway.
    if (
        host in {"ai-gateway.us.posthog.com", "ai-gateway.eu.posthog.com"}
        and str(team.organization_id) not in settings.POSTHOG_INTERNAL_ORG_IDS
    ):
        return False
    return (
        get_feature_flag_or_none(
            "llm-analytics-system-one-evaluations",
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            send_feature_flag_events=False,
        )
        is True
    )


class SystemOneRequestRejectedError(LLMError):
    pass


class SystemOneEndpointBlockedError(LLMError):
    pass


class SystemOneRateLimitError(RateLimitError):
    def __init__(self, retry_after: str | None) -> None:
        super().__init__("The System One endpoint is temporarily unavailable. Try again later.")
        self.retry_after: float | None = None
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    return
            if math.isfinite(delay):
                self.retry_after = max(1, min(delay, 60))


class SystemOneClient:
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
    ) -> SystemOneResult:
        try:
            base_url = SystemOneClient.normalize_base_url(base_url)
        except ValueError as error:
            raise SystemOneEndpointBlockedError(str(error)) from error
        try:
            verdict = validate_url_and_pin_ips(base_url)
            if not verdict.allowed:
                raise SSRFBlockedError(verdict.reason)
            with pinned_client(
                base_url,
                verdict.pinned_ips,
                timeout=timeout,
                total_timeout=timeout,
                follow_redirects=False,
                event_hooks={"response": [_tag_response]},
            ) as client:
                response = client.post(
                    f"{base_url}/systemone",
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    json=build_system_one_body(state=state, questions=questions, model=model),
                )
        except SSRFBlockedError as error:
            raise SystemOneEndpointBlockedError("This endpoint is not allowed. Use a public HTTPS endpoint.") from error
        except httpx.DecodingError as error:
            raise SystemOneRequestRejectedError(
                "The endpoint returned a compressed or oversized response. "
                "Configure it to return uncompressed responses no larger than 1 MiB."
            ) from error
        except httpx.RequestError as error:
            raise ProviderConnectionError("Could not reach the System One endpoint. Try again.") from error

        status = response.status_code
        if status == 200:
            try:
                return parse_system_one_response(response.json(), questions)
            except (ValueError, SystemOneRequestFailed) as error:
                raise StructuredOutputParseError(
                    "The endpoint returned an invalid System One response. Check compatibility."
                ) from error
        if status == 401:
            raise AuthenticationError("The endpoint rejected this credential. Check the bearer token.")
        if status == 403:
            raise ModelPermissionError(model)
        if status == 404:
            raise ModelNotFoundError(model)
        if status in (408, 429, 503, 529):
            raise SystemOneRateLimitError(response.headers.get("Retry-After"))
        if status >= 500:
            raise ProviderConnectionError("The System One endpoint is temporarily unavailable. Try again.")
        if 300 <= status < 400:
            raise SystemOneEndpointBlockedError("The endpoint redirected the request. Use its final HTTPS URL.")
        if status == 413 or (status == 422 and is_context_window_error_message(response.text)):
            raise ContextWindowExceededError("This input exceeds the endpoint's size limit. Reduce the input.")
        raise SystemOneRequestRejectedError(
            "The endpoint rejected the evaluation request. Check the model and criteria."
        )

    @staticmethod
    def validate_key(api_key: str, *, base_url: str, model: str) -> tuple[str, str | None]:
        try:
            SystemOneClient.evaluate(
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
            RateLimitError,
            StructuredOutputParseError,
            SystemOneEndpointBlockedError,
            SystemOneRequestRejectedError,
            ContextWindowExceededError,
        ) as error:
            return "error", str(error)
        return "ok", None
