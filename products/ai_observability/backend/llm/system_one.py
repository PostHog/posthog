import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, Field, ValidationError

from posthog.security.pinned_requests import SSRFBlockedError, pinned_request
from posthog.security.url_validation import has_authority_bypass_chars

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelNotFoundError,
    ModelPermissionError,
    ProviderConnectionError,
    RateLimitError,
    StructuredOutputParseError,
    is_context_window_error_message,
)


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)


class SystemOneUsage(BaseModel):
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)


class SystemOneResponse(BaseModel):
    model: str = Field(min_length=1)
    answers: dict[str, NoulAnswer]
    usage: SystemOneUsage


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
    BASE_URL = "https://api.typesafe.ai/v1"

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
    def evaluate_boolean(
        *, api_key: str, model: str, prompt: str, source: str, allows_na: bool, base_url: str = BASE_URL
    ) -> SystemOneResponse:
        base_url = SystemOneClient.normalize_base_url(base_url)
        if not api_key and base_url == SystemOneClient.BASE_URL:
            raise AuthenticationError("A TypeSafe API key is required.")
        questions = {"verdict": {"type": "noul", "instructions": prompt}}
        if allows_na:
            questions["applicable"] = {
                "type": "noul",
                "instructions": (
                    "Do these evaluation criteria apply to this input? Answer true when the criteria can be "
                    "evaluated, even if they are not met. Answer false only when they are not relevant.\n\n" + prompt
                ),
            }
        try:
            response = pinned_request(
                "POST",
                f"{base_url}/systemone",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json={"model": model, "state": source, "questions": questions},
                timeout=60,
            )
        except SSRFBlockedError as error:
            raise StructuredOutputParseError("This endpoint is not allowed. Use a public HTTPS endpoint.") from error
        except requests.RequestException as error:
            raise ProviderConnectionError("Could not reach the System One endpoint. Try again.") from error

        if response.status_code == 401:
            raise AuthenticationError("The endpoint rejected this credential. Check the bearer token.")
        if response.status_code == 403:
            raise ModelPermissionError(model)
        if response.status_code == 404:
            raise ModelNotFoundError(model)
        if response.status_code in (429, 503, 529):
            raise SystemOneRateLimitError(response.headers.get("Retry-After"))
        if response.status_code >= 500:
            raise ProviderConnectionError("The System One endpoint is temporarily unavailable. Try again.")
        if response.status_code == 413 or (
            response.status_code == 422 and is_context_window_error_message(response.text)
        ):
            raise ContextWindowExceededError("This input exceeds the endpoint's size limit. Reduce the input.")
        if response.status_code != 200:
            raise StructuredOutputParseError(
                "The endpoint rejected the evaluation request. Check the model and criteria."
            )
        try:
            result = SystemOneResponse.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise StructuredOutputParseError(
                "The endpoint returned an invalid System One response. Check compatibility."
            ) from error
        # boffin: Missing answers cannot become a false verdict.
        if not questions.keys() <= result.answers.keys():
            raise StructuredOutputParseError(
                "The endpoint did not answer every evaluation question. Check compatibility."
            )
        return result

    @staticmethod
    def validate_key(api_key: str, *, base_url: str = BASE_URL, model: str = MODEL) -> tuple[str, str | None]:
        try:
            SystemOneClient.evaluate_boolean(
                api_key=api_key,
                base_url=base_url,
                model=model,
                prompt="Does the text contain a greeting?",
                source="Hello!",
                allows_na=True,
            )
        except (AuthenticationError, ModelPermissionError) as error:
            return "invalid", str(error)
        except (
            ValueError,
            ModelNotFoundError,
            ProviderConnectionError,
            RateLimitError,
            StructuredOutputParseError,
            ContextWindowExceededError,
        ) as error:
            return "error", str(error)
        return "ok", None
