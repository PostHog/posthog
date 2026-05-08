"""Feature-flag scorers for sandboxed agent evals.

The scorer reads the agent's successful ``create-feature-flag`` MCP call and
the returned feature flag object, then judges whether the created entity
matches the intended configuration. This is deliberately about the MCP-world
artifact, not Max's internal ``create_feature_flag`` tool trajectory.
"""

import re
import json
from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser, ToolCall

CREATE_FEATURE_FLAG_TOOL_NAME = "create-feature-flag"
FEATURE_FLAG_UNRELATED_WRITE_TOOLS = frozenset(
    {
        "dashboard-create",
        "delete-feature-flag",
        "experiment-create",
        "feature-flags-bulk-delete-create",
        "feature-flags-bulk-update-tags-create",
        "feature-flags-copy-flags-create",
        "feature-flags-create-static-cohort-for-flag-create",
        "feature-flags-dashboard-create",
        "feature-flags-enrich-usage-dashboard-create",
        "insight-create",
        "insight-destroy",
        "insight-partial-update",
        "insight-update",
        "scheduled-changes-create",
        "survey-create",
        "survey-delete",
        "survey-update",
        "surveys-duplicate-to-projects-create",
        "surveys-generate-translations-create",
    }
)
BINARY_CHOICE_SCORES = {"pass": 1.0, "fail": 0.0}
JUDGE_MODEL = "gpt-5.4"
_ID_RE = re.compile(r'"id"\s*:\s*(\d+)|\bID\s*[:#]?\s*(\d+)|/feature_flags/(\d+)')
_KEY_RE = re.compile(r'"key"\s*:\s*"([^"]+)"|\bkey\s*[:=]\s*([a-zA-Z0-9_-]+)')


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _safe_json_loads(value: str) -> Any | None:
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None


def _find_feature_flag_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        parsed = _safe_json_loads(value)
        if parsed is None or parsed == value:
            return None
        return _find_feature_flag_payload(parsed)

    if isinstance(value, dict):
        if isinstance(value.get("key"), str) and ("id" in value or "filters" in value or "active" in value):
            return value

        # ACP/MCP result shapes commonly wrap the text response one or two
        # levels down. Walk the small structured payload rather than relying
        # on one exact transport shape.
        for nested in value.values():
            found = _find_feature_flag_payload(nested)
            if found is not None:
                return found
        return None

    if isinstance(value, list):
        for item in value:
            found = _find_feature_flag_payload(item)
            if found is not None:
                return found
    return None


def _extract_created_feature_flag(tool_output: str) -> dict[str, Any] | None:
    parsed = _safe_json_loads(tool_output)
    if parsed is None:
        id_match = _ID_RE.search(tool_output)
        key_match = _KEY_RE.search(tool_output)
        if id_match is None and key_match is None:
            return None

        fallback: dict[str, Any] = {}
        if id_match is not None:
            fallback["id"] = next(group for group in id_match.groups() if group is not None)
        if key_match is not None:
            fallback["key"] = next(group for group in key_match.groups() if group is not None)
        return fallback

    return _find_feature_flag_payload(parsed)


def _last_successful_create(output: dict[str, Any] | None) -> ToolCall | None:
    parser = _parser_for(output)
    if parser is None:
        return None
    successful = [call for call in parser.get_tool_calls(CREATE_FEATURE_FLAG_TOOL_NAME) if not call.is_error]
    if not successful:
        return None
    return successful[-1]


class CreateFeatureFlagToolAttempted(Scorer):
    """Binary: did the agent attempt the required feature-flag creation tool?

    Unlike ``RequiredToolCall``, this scorer accepts errored tool calls. That
    makes the failure mode explicit: an agent that selected the right MCP tool
    but hit a validation/API error should pass this trajectory check while
    failing the outcome scorer.
    """

    def __init__(self, *, name: str = "create_feature_flag_tool_attempted") -> None:
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        return self._evaluate(output)

    def _run_eval_sync(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        return self._evaluate(output)

    def _evaluate(self, output: dict[str, Any] | None) -> Score:
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        calls = parser.get_tool_calls(CREATE_FEATURE_FLAG_TOOL_NAME)
        if not calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"Agent never attempted {CREATE_FEATURE_FLAG_TOOL_NAME}"},
            )

        errored = [call for call in calls if call.is_error]
        successful = [call for call in calls if not call.is_error]
        last_call = calls[-1]
        return Score(
            name=self._name(),
            score=1.0,
            metadata={
                "attempt_count": len(calls),
                "successful_count": len(successful),
                "errored_count": len(errored),
                "last_call_error": last_call.is_error,
                "last_call_output": last_call.output[:1000],
            },
        )


class FeatureFlagCreationAccuracy(LLMClassifier):
    """Binary judge: did the created feature flag match the expected intent?"""

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(spec, dict):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No expected feature flag spec"})

        call = _last_successful_create(output)
        if call is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"Agent never ran {CREATE_FEATURE_FLAG_TOOL_NAME} successfully"},
            )

        created_feature_flag = _extract_created_feature_flag(call.output)
        return {
            "output": {
                "prompt": output.get("prompt", "") if output else "",
                "tool_input": call.input,
                "created_feature_flag": created_feature_flag,
                "tool_output": call.output[:4000],
            },
            "expected": spec,
        }

    async def _run_eval_async(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return await super()._run_eval_async(prepared["output"], prepared["expected"], **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _run_eval_sync(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return super()._run_eval_sync(prepared["output"], prepared["expected"], **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="feature_flag_creation_accuracy",
            prompt_template="""
You are judging whether an agent correctly created a PostHog feature flag through the `create-feature-flag` MCP tool.

The bar is semantic correctness of the created entity. Prefer the returned `created_feature_flag` because it is the API result. If it is unavailable but the successful tool call input clearly contains the required configuration, you may use `tool_input` as evidence that the accepted MCP call had the right shape.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Expected configuration:
<expected>
{{expected}}
</expected>

Actual successful MCP tool input:
<tool_input>
{{output.tool_input}}
</tool_input>

Feature flag returned by the MCP tool:
<created_feature_flag>
{{output.created_feature_flag}}
</created_feature_flag>

Raw tool output, if needed:
<tool_output>
{{output.tool_output}}
</tool_output>

Evaluate these material requirements:
- The feature flag was created with the expected exact `key`.
- If `active` is specified, the created flag's active state matches it.
- If `rollout_percentage` is specified, a release-condition group has that rollout percentage.
- If `property_filters` are specified, the created flag has equivalent filters under `filters.groups[*].properties` with the same key, operator, value, and type.
- If `variants` are specified, the created flag is multivariate and has equivalent variant keys and rollout percentages. Variant names are cosmetic.
- Ignore cosmetic differences in `name` unless the key or functional configuration is wrong.
- Do not require extra fields that the prompt did not ask for.

Choose `pass` only if all expected requirements are met. Otherwise choose `fail`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class CreatedFeatureFlagIdInOutput(Scorer):
    """Binary: does the final assistant message include the created flag ID?"""

    def __init__(self, *, name: str = "created_feature_flag_id_in_output") -> None:
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        return self._evaluate(output)

    def _run_eval_sync(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        return self._evaluate(output)

    def _evaluate(self, output: dict[str, Any] | None) -> Score:
        call = _last_successful_create(output)
        if call is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"Agent never ran {CREATE_FEATURE_FLAG_TOOL_NAME} successfully"},
            )

        created_feature_flag = _extract_created_feature_flag(call.output)
        if not created_feature_flag:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Could not parse created feature flag"})

        flag_id = created_feature_flag.get("id")
        if flag_id is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Created feature flag had no id"})

        last_message = output.get("last_message", "") if output else ""
        if not isinstance(last_message, str):
            last_message = str(last_message)

        expected_id = str(flag_id)
        if expected_id not in last_message:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "Created feature flag ID not present in final assistant message",
                    "expected_id": expected_id,
                },
            )

        return Score(
            name=self._name(),
            score=1.0,
            metadata={"expected_id": expected_id, "key": created_feature_flag.get("key")},
        )
