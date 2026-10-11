from collections.abc import Mapping
from typing import cast

import openai

from posthog.llm.system_one import (
    ChoiceQuestion,
    JsonValue,
    NoulQuestion,
    Question,
    ScoreQuestion,
    SystemOneRequestFailed,
    SystemOneResult,
    parse_system_one_response,
)

from products.ai_observability.backend.llm.decisions import DecisionRateLimitError
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ProviderConnectionError,
    ProviderRequestRejectedError,
    QuotaExceededError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.llm.providers._diagnostics import tagged_http_client
from products.ai_observability.backend.llm.providers.openai import OPENAI_DECISIONS_BASE_URL, OpenAIAdapter


class OpenAIDecisionAdapter(OpenAIAdapter):
    @staticmethod
    def _text(value: JsonValue) -> str:
        if not isinstance(value, str):
            raise ValueError("OpenAI decision criteria must be text.")
        return value

    @classmethod
    def _question(cls, name: str, question: Question) -> dict[str, JsonValue]:
        instructions = cls._text(question.instructions)
        body: dict[str, JsonValue] = {"name": name, "instructions": instructions}
        if isinstance(question, NoulQuestion):
            body["type"] = "predicate"
            for label, criteria in (("True", question.criteria_true), ("False", question.criteria_false)):
                if criteria is not None:
                    instructions += f"\n{label}: {cls._text(criteria)}"
            body["instructions"] = instructions
        elif isinstance(question, ChoiceQuestion):
            if len(question.criteria) < 2:
                raise ValueError("OpenAI decision choices require at least two options.")
            body["type"] = "choice"
            body["choices"] = [
                {"value": value, **({"description": cls._text(description)} if description is not None else {})}
                for value, description in question.criteria.items()
            ]
        else:
            body["type"] = "score"
            body["levels"] = [
                {"label": str(index), "description": cls._text(criteria)}
                for index, criteria in enumerate(question.criteria)
            ]
        return body

    @staticmethod
    def _probabilities(raw: object, question: ChoiceQuestion | ScoreQuestion) -> dict[str, JsonValue]:
        if not isinstance(raw, list):
            raise ValueError("The OpenAI decision response contains invalid probabilities.")
        options = (
            set(question.criteria)
            if isinstance(question, ChoiceQuestion)
            else {str(index) for index in range(len(question.criteria))}
        )
        probabilities: dict[str, JsonValue] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("The OpenAI decision response contains an invalid probability.")
            value = item.get("value")
            if isinstance(question, ScoreQuestion):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError("The OpenAI decision response contains an invalid score level.")
                value = str(value)
            if not isinstance(value, str) or value not in options or value in probabilities:
                raise ValueError("The OpenAI decision response contains an unexpected or duplicate option.")
            probabilities[value] = item.get("probability")
        return probabilities

    @classmethod
    def _parse(cls, payload: object, questions: Mapping[str, Question]) -> SystemOneResult:
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), list):
            raise ValueError("The OpenAI decision response contains no answers.")
        answers: dict[str, JsonValue] = {}
        for raw in payload["answers"]:
            if not isinstance(raw, dict):
                raise ValueError("The OpenAI decision response contains an invalid answer.")
            name = raw.get("name")
            if not isinstance(name, str) or name not in questions or name in answers:
                raise ValueError("The OpenAI decision response contains an unexpected or duplicate answer.")
            answer = dict(raw)
            question = questions[name]
            expected_type = (
                "predicate"
                if isinstance(question, NoulQuestion)
                else "choice"
                if isinstance(question, ChoiceQuestion)
                else "score"
            )
            if answer.get("type") not in (expected_type, "refusal"):
                raise ValueError("The OpenAI decision response contains an unexpected answer type.")
            if answer.get("type") == "predicate":
                answer["type"] = "noul"
                answer["noul"] = answer.pop("probability", None)
            elif answer.get("type") in ("choice", "score"):
                assert isinstance(question, ChoiceQuestion | ScoreQuestion)
                answer["probabilities"] = cls._probabilities(answer.get("probabilities"), question)
            answers[name] = cast(JsonValue, answer)
        # The shared parser validates answer types, finite scores, and every requested option.
        return parse_system_one_response({**payload, "answers": answers}, questions)

    def evaluate(
        self,
        *,
        api_key: str,
        model: str,
        state: str,
        questions: Mapping[str, Question],
    ) -> SystemOneResult:
        if not api_key:
            raise AuthenticationError("Add an OpenAI API key to run decision evaluations.")
        try:
            body = {
                "model": model,
                "input": state,
                "questions": [self._question(name, q) for name, q in questions.items()],
            }
        except ValueError as error:
            raise ProviderRequestRejectedError(str(error)) from error
        try:
            with openai.OpenAI(
                api_key=api_key,
                base_url=OPENAI_DECISIONS_BASE_URL,
                max_retries=0,
                timeout=60,
                http_client=tagged_http_client(timeout=60, follow_redirects=False),
            ) as client:
                # The installed SDK's generic POST supports this endpoint without a repo-wide SDK upgrade.
                payload = client.post("/decisions", body=body, cast_to=object)
            return self._parse(payload, questions)
        except openai.APIError as error:
            mapped = self._mapped_error(error, model)
            if isinstance(error, openai.RateLimitError) and not isinstance(mapped, QuotaExceededError):
                raise DecisionRateLimitError(error.response.headers.get("Retry-After")) from error
            if mapped is not None:
                raise mapped from error
            if isinstance(error, openai.APIStatusError):
                if error.status_code >= 500 or error.status_code in (408, 409) or 300 <= error.status_code < 400:
                    raise ProviderConnectionError(
                        "The OpenAI decision endpoint is temporarily unavailable. Try again."
                    ) from error
            raise ProviderRequestRejectedError(
                "OpenAI rejected the decision request. Check the model and criteria."
            ) from error
        except (ValueError, SystemOneRequestFailed) as error:
            raise StructuredOutputParseError("OpenAI returned an invalid decision response.") from error
