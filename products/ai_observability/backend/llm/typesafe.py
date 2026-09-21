import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal

import requests
from pydantic import BaseModel, Field, ValidationError

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


class TypeSafeUsage(BaseModel):
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)


class TypeSafeResponse(BaseModel):
    model: str = Field(min_length=1)
    answers: dict[str, NoulAnswer]
    usage: TypeSafeUsage


class TypeSafeRateLimitError(RateLimitError):
    def __init__(self, retry_after: str | None) -> None:
        super().__init__("TypeSafe is temporarily rate limiting requests.")
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


class TypeSafeClient:
    MODEL = "jev-1.13.0"

    @staticmethod
    def evaluate_boolean(*, api_key: str, model: str, prompt: str, source: str, allows_na: bool) -> TypeSafeResponse:
        if not api_key:
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
            response = requests.request(
                "POST",
                "https://api.typesafe.ai/v1/systemone",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "state": source, "questions": questions},
                timeout=60,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise ProviderConnectionError("Could not reach TypeSafe.") from error

        if response.status_code == 401:
            raise AuthenticationError("TypeSafe rejected this API key.")
        if response.status_code == 403:
            raise ModelPermissionError(model)
        if response.status_code == 404:
            raise ModelNotFoundError(model)
        if response.status_code in (429, 529):
            raise TypeSafeRateLimitError(response.headers.get("Retry-After"))
        if response.status_code >= 500:
            raise ProviderConnectionError("TypeSafe is temporarily unavailable.")
        if response.status_code == 422 and is_context_window_error_message(response.text):
            raise ContextWindowExceededError("This input exceeds Jev's context window.")
        if response.status_code != 200:
            raise StructuredOutputParseError("TypeSafe rejected the evaluation request. Check the model and criteria.")
        try:
            result = TypeSafeResponse.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise StructuredOutputParseError("TypeSafe returned an invalid evaluation response.") from error
        # boffin: Missing answers cannot become a false verdict.
        if not questions.keys() <= result.answers.keys():
            raise StructuredOutputParseError("TypeSafe did not answer every evaluation question.")
        return result

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        try:
            response = requests.request(
                "GET",
                "https://api.typesafe.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException:
            return "error", "Could not reach TypeSafe. Try again."
        if response.status_code == 200:
            return "ok", None
        if response.status_code in (401, 403):
            return "invalid", "TypeSafe rejected this API key. Check the key and try again."
        return "error", "Could not validate the TypeSafe key. Try again."
