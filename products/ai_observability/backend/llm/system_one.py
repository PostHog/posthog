import math
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from django.conf import settings

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe.client import (
    TYPESAFE_API_BASE,
    JsonValue,
    NoulQuestion,
    Question,
    SystemOneResult,
    TypeSafeNotConfigured,
    TypeSafeRequestFailed,
    system_one,
)
from posthog.egress.typesafe.transport import TypeSafeEgressBudgetExhausted
from posthog.models import Team
from posthog.ph_client import get_feature_flag_or_none
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
from posthog.security.url_validation import has_authority_bypass_chars

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


def system_one_evaluations_enabled(team_id: int) -> bool:
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    # Staff access to a customer project does not make its data eligible for this experiment.
    if str(team.organization_id) not in settings.POSTHOG_INTERNAL_ORG_IDS:
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


class SystemOneRateLimitError(RateLimitError):
    def __init__(self, retry_after: str | None) -> None:
        super().__init__("The System One endpoint is busy. Try again later.")
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
                self.retry_after = max(1, min(delay, 300))


class SystemOneClient:
    MODEL = "jev-1.13.0"
    BASE_URL = f"{TYPESAFE_API_BASE}/v1"

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
        return base_url.rstrip("/")

    @staticmethod
    def evaluate(
        *,
        api_key: str,
        model: str,
        state: JsonValue,
        questions: Mapping[str, Question],
        base_url: str = BASE_URL,
        priority: Priority = Priority.BATCH,
    ) -> SystemOneResult:
        base_url = SystemOneClient.normalize_base_url(base_url)
        if not api_key and base_url == SystemOneClient.BASE_URL:
            raise AuthenticationError("A TypeSafe API key is required.")
        try:
            with pinned_session(f"{base_url}/systemone") as session:
                result = system_one(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    state=state,
                    questions=questions,
                    source="llma_evaluations",
                    priority=priority,
                    timeout=60,
                    session=session,
                )
            if result.input_tokens is None or result.output_tokens is None:
                raise StructuredOutputParseError("The endpoint returned invalid token usage. Check compatibility.")
            return result
        except TypeSafeNotConfigured as error:
            raise AuthenticationError("A TypeSafe API key is required.") from error
        except TypeSafeEgressBudgetExhausted as error:
            raise SystemOneRateLimitError(None) from error
        except SSRFBlockedError as error:
            raise SystemOneRequestRejectedError("This endpoint is not allowed. Use a public HTTPS endpoint.") from error
        except requests.RequestException as error:
            raise ProviderConnectionError("Could not reach the System One endpoint. Try again.") from error
        except TypeSafeRequestFailed as error:
            status = error.status_code
            response = error.response
            if status is None:
                raise StructuredOutputParseError(
                    "The endpoint returned an invalid System One response. Check compatibility."
                ) from error
            if status == 401:
                raise AuthenticationError("The endpoint rejected this credential. Check the bearer token.") from error
            if status == 403:
                raise ModelPermissionError(model) from error
            if status == 404:
                raise ModelNotFoundError(model) from error
            if status in (429, 503, 529):
                raise SystemOneRateLimitError(
                    response.headers.get("Retry-After") if response is not None else None
                ) from error
            if status >= 500:
                raise ProviderConnectionError(
                    "The System One endpoint is temporarily unavailable. Try again."
                ) from error
            if status == 413 or (
                status == 422 and response is not None and is_context_window_error_message(response.text)
            ):
                raise ContextWindowExceededError(
                    "This input exceeds the endpoint's size limit. Reduce the input."
                ) from error
            raise SystemOneRequestRejectedError(
                "The endpoint rejected the evaluation request. Check the model and criteria."
            ) from error

    @staticmethod
    def validate_key(api_key: str, *, base_url: str = BASE_URL, model: str = MODEL) -> tuple[str, str | None]:
        try:
            SystemOneClient.evaluate(
                api_key=api_key,
                base_url=base_url,
                model=model,
                state="Hello!",
                priority=Priority.NORMAL,
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
            SystemOneRequestRejectedError,
            ContextWindowExceededError,
        ) as error:
            return "error", str(error)
        return "ok", None
