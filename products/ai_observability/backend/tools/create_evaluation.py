import uuid
from typing import Any, Literal

from django.http import HttpRequest

from pydantic import BaseModel, Field
from rest_framework.request import Request

from posthog.schema import AssistantTool

from posthog.sync import database_sync_to_async

from products.ai_observability.backend.api.evaluations import EvaluationSerializer, save_new_evaluation
from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.provider_keys import LLMProvider

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

TOOL_DESCRIPTION = """Create an online evaluation for this project. It is always created disabled.

# When to use this tool
- The user picked one or more evaluations you proposed and asked you to create them.
- Never create an evaluation the user did not ask for.

# Before calling it
- For `hog`, test the exact `source` with `run_hog_eval_test` first, using the same `target`, `output_type` and `output_config`.
- For `llm_judge`, write `prompt` as instructions to a judge that sees the input and output. You cannot test a judge here.
- For `sentiment`, no prompt or source is needed. It only supports the `generation` target.

# After calling it
The evaluation does not run until a person enables it. Give the user the returned link so they can review it, test it and enable it.
An `llm_judge` evaluation also needs a provider API key before it can be enabled; say so when the result reports that the team has none.
"""

EvaluationType = Literal["hog", "llm_judge", "sentiment"]


class CreateEvaluationArgs(BaseModel):
    name: str = Field(min_length=1, max_length=400, description="Short name that says what the evaluation checks")
    description: str = Field(default="", description="One or two sentences on the failure mode this guards against")
    evaluation_type: EvaluationType = Field(
        description="'hog' for deterministic code checks (no API key needed), 'llm_judge' for an LLM judge, 'sentiment' for user sentiment"
    )
    source: str | None = Field(default=None, description="Hog source code. Required for 'hog'.")
    prompt: str | None = Field(default=None, description="Judge instructions. Required for 'llm_judge'.")
    output_type: Literal["boolean", "numeric", "categorical"] = Field(
        default="boolean", description="Result type. Use 'boolean' for pass/fail checks."
    )
    output_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Output settings, matching what you tested: allows_na, true_is_failure for boolean; min, max and passing_rule for numeric; options and passing_rule for categorical",
    )
    target: Literal["generation", "trace", "session"] = Field(
        default="generation", description="What one evaluation run scores"
    )
    rollout_percentage: float = Field(
        default=100,
        gt=0,
        le=100,
        description="Share of matching events to evaluate once enabled. Lower it for high-volume projects.",
    )


class CreateEvaluationTool(MaxTool):
    name: str = AssistantTool.CREATE_EVALUATION.value
    description: str = TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateEvaluationArgs

    def get_required_resource_access(self):
        return [("evaluation", "editor")]

    async def _arun_impl(
        self,
        name: str,
        evaluation_type: EvaluationType,
        description: str = "",
        source: str | None = None,
        prompt: str | None = None,
        output_type: Literal["boolean", "numeric", "categorical"] = "boolean",
        output_config: dict[str, Any] | None = None,
        target: Literal["generation", "trace", "session"] = "generation",
        rollout_percentage: float = 100,
    ) -> tuple[str, dict[str, Any]]:
        return await database_sync_to_async(self._create)(
            name=name,
            description=description,
            evaluation_type=evaluation_type,
            source=source,
            prompt=prompt,
            output_type=output_type,
            output_config=output_config or {},
            target=target,
            rollout_percentage=rollout_percentage,
        )

    def _create(
        self,
        *,
        name: str,
        description: str,
        evaluation_type: EvaluationType,
        source: str | None,
        prompt: str | None,
        output_type: str,
        output_config: dict[str, Any],
        target: str,
        rollout_percentage: float,
    ) -> tuple[str, dict[str, Any]]:
        if evaluation_type == "sentiment":
            # Sentiment has its own fixed output; the boolean/numeric/categorical arguments do not apply.
            output_type, output_config = "sentiment", {}
        data: dict[str, Any] = {
            "name": name,
            "description": description,
            "enabled": False,
            "evaluation_type": evaluation_type,
            "evaluation_config": self._evaluation_config(evaluation_type, source, prompt),
            "output_type": output_type,
            "output_config": output_config,
            "target": target,
            "conditions": [{"id": str(uuid.uuid4()), "rollout_percentage": rollout_percentage, "properties": []}],
        }
        has_key = True
        if evaluation_type == "llm_judge":
            data["model_configuration"], has_key = self._judge_model_configuration()

        serializer = EvaluationSerializer(
            data=data, context={"request": self._request(), "get_team": lambda: self._team}
        )
        if not serializer.is_valid():
            raise MaxToolRetryableError(f"The evaluation is invalid: {serializer.errors}")
        evaluation = save_new_evaluation(serializer, user=self._user, team=self._team, source="posthog_ai")

        url = f"/project/{self._team.id}/ai-evals/evaluations/{evaluation.id}"
        lines = [f"Created the evaluation, disabled. Review and enable it here: {url}"]
        if not has_key:
            lines.append("This project has no provider API key, so the user must add one before enabling this judge.")
        return "\n".join(lines), {"evaluation_id": str(evaluation.id), "url": url}

    @staticmethod
    def _evaluation_config(evaluation_type: EvaluationType, source: str | None, prompt: str | None) -> dict[str, Any]:
        if evaluation_type == "hog":
            if not source:
                raise MaxToolRetryableError("Pass `source` for a hog evaluation.")
            return {"source": source}
        if evaluation_type == "llm_judge":
            if not prompt:
                raise MaxToolRetryableError("Pass `prompt` for an llm_judge evaluation.")
            return {"prompt": prompt}
        return {"source": "user_messages"}

    def _judge_model_configuration(self) -> tuple[dict[str, Any], bool]:
        """Pin the team's active key with its provider's default model, as the editor does when a key is picked.

        Without a usable key, fall back to the OpenAI default so the draft saves; enabling it then asks for a key.
        """
        config = EvaluationConfig.objects.filter(team=self._team).select_related("active_provider_key").first()
        active_key = config.active_provider_key if config else None
        if active_key is not None and active_key.provider in DEFAULT_MODEL_BY_PROVIDER:
            model_configuration = {
                "provider": active_key.provider,
                "model": DEFAULT_MODEL_BY_PROVIDER[active_key.provider],
                "provider_key_id": str(active_key.id),
            }
            return model_configuration, True
        provider = LLMProvider.OPENAI.value
        return {"provider": provider, "model": DEFAULT_MODEL_BY_PROVIDER[provider], "provider_key_id": None}, False

    def _request(self) -> Request:
        # The serializer reads the creating user from the request; the tool has no HTTP request of its own.
        request = Request(HttpRequest())
        request.user = self._user
        return request
