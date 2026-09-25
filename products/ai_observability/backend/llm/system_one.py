import math
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, Field, JsonValue, ValidationError

from posthog.security.pinned_requests import SSRFBlockedError, pinned_request
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

type SystemOneContent = str | dict[str, JsonValue] | list[JsonValue]
type Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: SystemOneContent | None = None
    criteria: dict[Literal["true", "false"], SystemOneContent | None] | None = None


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: SystemOneContent | None = None
    criteria: list[SystemOneContent] = Field(min_length=1, max_length=10)


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: SystemOneContent | None = None
    criteria: dict[str, SystemOneContent | None] = Field(min_length=1, max_length=255)


type SystemOneQuestion = NoulQuestion | ScoreQuestion | ChoiceQuestion


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: Probability


class ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float = Field(strict=True, ge=0, allow_inf_nan=False)
    legend: dict[str, SystemOneContent]
    probabilities: dict[str, Probability]
    confidence: Probability


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, Probability]
    confidence: Probability


class SystemOneUsage(BaseModel):
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)


class SystemOneResponse(BaseModel):
    model: str = Field(min_length=1)
    answers: dict[str, Annotated[NoulAnswer | ScoreAnswer | ChoiceAnswer, Field(discriminator="type")]]
    usage: SystemOneUsage


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
    def evaluate(
        *,
        api_key: str,
        model: str,
        state: SystemOneContent,
        questions: Mapping[str, SystemOneQuestion],
        base_url: str = BASE_URL,
    ) -> SystemOneResponse:
        base_url = SystemOneClient.normalize_base_url(base_url)
        if not api_key and base_url == SystemOneClient.BASE_URL:
            raise AuthenticationError("A TypeSafe API key is required.")
        if not questions:
            raise ValueError("Provide at least one System One question.")
        try:
            response = pinned_request(
                "POST",
                f"{base_url}/systemone",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json={
                    "model": model,
                    "state": state,
                    "questions": {
                        key: question.model_dump(mode="json", exclude_none=True) for key, question in questions.items()
                    },
                },
                timeout=60,
            )
        except SSRFBlockedError as error:
            raise SystemOneRequestRejectedError("This endpoint is not allowed. Use a public HTTPS endpoint.") from error
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
            raise SystemOneRequestRejectedError(
                "The endpoint rejected the evaluation request. Check the model and criteria."
            )
        try:
            result = SystemOneResponse.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise StructuredOutputParseError(
                "The endpoint returned an invalid System One response. Check compatibility."
            ) from error
        # Missing or mismatched answers cannot become valid evaluation results.
        if not questions.keys() <= result.answers.keys():
            raise StructuredOutputParseError(
                "The endpoint did not answer every evaluation question. Check compatibility."
            )
        for key, question in questions.items():
            answer = result.answers[key]
            if answer.type != question.type:
                raise StructuredOutputParseError("The endpoint returned the wrong answer type. Check compatibility.")
            if isinstance(question, ChoiceQuestion) and isinstance(answer, ChoiceAnswer):
                if set(answer.probabilities) != set(question.criteria) or answer.choice not in question.criteria:
                    raise StructuredOutputParseError("The endpoint returned different choices. Check compatibility.")
            if isinstance(question, ScoreQuestion) and isinstance(answer, ScoreAnswer):
                levels = {str(index) for index in range(len(question.criteria))}
                if (
                    set(answer.probabilities) != levels
                    or set(answer.legend) != levels
                    or answer.score > len(levels) - 1
                ):
                    raise StructuredOutputParseError(
                        "The endpoint returned an invalid score scale. Check compatibility."
                    )
            # Compatible servers round each probability to four decimal places.
            if isinstance(answer, ScoreAnswer | ChoiceAnswer) and not math.isclose(
                sum(answer.probabilities.values()), 1.0, abs_tol=max(0.001, len(answer.probabilities) * 0.00005)
            ):
                raise StructuredOutputParseError(
                    "The endpoint returned an invalid probability distribution. Check compatibility."
                )
        return result

    @staticmethod
    def validate_key(api_key: str, *, base_url: str = BASE_URL, model: str = MODEL) -> tuple[str, str | None]:
        try:
            SystemOneClient.evaluate(
                api_key=api_key,
                base_url=base_url,
                model=model,
                state="Hello!",
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
