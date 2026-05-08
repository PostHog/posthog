"""Survey scorers for sandboxed agent evals."""

from __future__ import annotations

import re
import json
from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser, ToolCall

SURVEY_CREATE_TOOL_NAME = "survey-create"
SURVEY_FORBIDDEN_WRITE_TOOLS = frozenset(
    {
        "survey-update",
        "survey-delete",
        "create-feature-flag",
        "update-feature-flag",
        "delete-feature-flag",
        "feature-flags-bulk-delete-create",
        "feature-flags-bulk-keys-create",
        "feature-flags-bulk-update-tags-create",
        "feature-flags-copy-flags-create",
        "scheduled-changes-create",
        "scheduled-changes-delete",
        "scheduled-changes-update",
        "scheduled-changes-update-full",
    }
)

GRADED_ALIGNMENT_CHOICE_SCORES = {
    "perfect": 1.0,
    "near_perfect": 0.9,
    "slightly_off": 0.75,
    "somewhat_misaligned": 0.5,
    "strongly_misaligned": 0.25,
    "useless": 0.0,
}

GRADED_ALIGNMENT_RUBRIC = """
How would you rate the alignment of the generated survey-create payload with the expected survey? Choose one:
- perfect: The payload fully matches the expected survey on every material aspect.
- near_perfect: The payload matches with at most one immaterial detail missed from the user question.
- slightly_off: Mostly matches, with minor discrepancies that may slightly change the created survey.
- somewhat_misaligned: Has some correct elements, but misses key aspects of the expected survey.
- strongly_misaligned: Does not match the expected survey and fails to address the user request.
- useless: Basically incomprehensible.

Details matter greatly here, especially question type, launch state, targeting, and feature-flag variant conditions.
""".strip()

_JUDGE_MODEL = "gpt-5.4"
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_ID_FIELD_RE = re.compile(r"\bid\s*[:=]\s*['\"]?([0-9a-fA-F-]{32,36})")


class _JudgedScorer(LLMClassifier):
    async def _run_eval_async(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return await super()._run_eval_async(prepared["output"], prepared["expected"], **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _run_eval_sync(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return super()._run_eval_sync(prepared["output"], prepared["expected"], **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        raise NotImplementedError


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _user_prompt(output: dict[str, Any] | None) -> str:
    parser = _parser_for(output)
    if parser is not None:
        return parser.get_user_prompt()
    if output:
        prompt = output.get("prompt")
        if isinstance(prompt, str):
            return prompt
    return ""


def _last_survey_create_call(output: dict[str, Any] | None, *, successful: bool | None = None) -> ToolCall | None:
    parser = _parser_for(output)
    if parser is None:
        return None
    calls = parser.get_tool_calls(SURVEY_CREATE_TOOL_NAME)
    if successful is True:
        calls = [call for call in calls if not call.is_error]
    elif successful is False:
        calls = [call for call in calls if call.is_error]
    if not calls:
        return None
    return calls[-1]


def extract_last_survey_create_input(output: dict[str, Any] | None) -> dict[str, Any] | None:
    call = _last_survey_create_call(output, successful=True)
    return call.input if call is not None else None


def _decode_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _survey_create_experienced_error(call: ToolCall) -> bool:
    if call.is_error:
        return True

    decoded = _decode_json(call.output)
    if isinstance(decoded, dict):
        for key in ("is_error", "isError"):
            value = decoded.get(key)
            if isinstance(value, bool) and value:
                return True

        for key in ("error", "errors"):
            value = decoded.get(key)
            if value:
                return True

    output_lower = call.output.lower()
    has_error_word = any(word in output_lower for word in ("error", "invalid", "required", "validation"))
    return has_error_word and "question" in output_lower


def _strip_analytics(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "_analytics"}


def _structured_result(call: ToolCall) -> dict[str, Any] | None:
    decoded = _decode_json(call.output)
    if isinstance(decoded, dict):
        structured = decoded.get("structuredContent")
        if isinstance(structured, dict):
            return _strip_analytics(structured)
        content = decoded.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if not isinstance(text, str):
                    continue
                text_decoded = _decode_json(text)
                if isinstance(text_decoded, dict):
                    return text_decoded
        if "id" in decoded:
            return decoded
    return None


def _extract_survey_id(call: ToolCall) -> str | None:
    structured = _structured_result(call)
    if structured is not None:
        survey_id = structured.get("id")
        if isinstance(survey_id, (str, int)):
            return str(survey_id)
        survey = structured.get("survey")
        if isinstance(survey, dict):
            nested_id = survey.get("id")
            if isinstance(nested_id, (str, int)):
                return str(nested_id)

    id_match = _ID_FIELD_RE.search(call.output)
    if id_match:
        return id_match.group(1)
    uuid_match = _UUID_RE.search(call.output)
    if uuid_match:
        return uuid_match.group(0)
    return None


def _expected_spec(expected: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(expected, dict):
        return None
    spec = expected.get(key)
    return spec if isinstance(spec, dict) else None


def _seeded_flag_id(output: dict[str, Any] | None, flag_key: str) -> int | None:
    if not output:
        return None
    seed = output.get("seed")
    if not isinstance(seed, dict):
        return None
    flags_by_key = seed.get("feature_flags_by_key")
    if not isinstance(flags_by_key, dict):
        return None
    flag = flags_by_key.get(flag_key)
    if not isinstance(flag, dict):
        return None
    flag_id = flag.get("id")
    return flag_id if isinstance(flag_id, int) else None


def _materialize_expected_survey(
    expected: dict[str, Any] | None,
    output: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    spec = _expected_spec(expected, "survey_create_alignment")
    if spec is None:
        return None, "No expected.survey_create_alignment provided"

    survey = json.loads(json.dumps(spec))
    linked_flag_key = survey.pop("linked_flag_key", None)
    if isinstance(linked_flag_key, str):
        flag_id = _seeded_flag_id(output, linked_flag_key)
        if flag_id is None:
            return None, f"No seeded feature flag found for key '{linked_flag_key}'"
        survey["linked_flag_id"] = flag_id
    return survey, None


class SurveyCreationSuccess(Scorer):
    """Binary: did survey-create succeed when expected, or avoid success for invalid input?"""

    def _name(self) -> str:
        return "survey_created"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> Score:
        spec = _expected_spec(expected, self._name()) or {}
        should_create = spec.get("should_create", True)
        successful_call = _last_survey_create_call(output, successful=True)

        if should_create:
            if successful_call is None:
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={"reason": "Agent never ran survey-create successfully"},
                )
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"survey_id": _extract_survey_id(successful_call)},
            )

        if successful_call is None:
            return Score(name=self._name(), score=1.0, metadata={})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "survey-create succeeded but this case expected no survey",
                "input": successful_call.input,
            },
        )


class SurveyCreateOutcome(Scorer):
    """Binary: did the eval take the expected survey-create path?

    Creation cases should produce exactly one successful ``survey-create`` call.
    Rejection cases should experience a ``survey-create`` error and never create
    a survey successfully.
    """

    def _name(self) -> str:
        return "survey_create_outcome"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> Score:
        spec = _expected_spec(expected, "survey_created") or {}
        should_create = spec.get("should_create", True)
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        calls = parser.get_tool_calls(SURVEY_CREATE_TOOL_NAME)
        if not calls:
            return Score(name=self._name(), score=0.0, metadata={"reason": "survey-create was never attempted"})

        successful_calls = [call for call in calls if not _survey_create_experienced_error(call)]
        error_calls = [call for call in calls if _survey_create_experienced_error(call)]

        if should_create:
            if not successful_calls:
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={
                        "reason": "survey-create never succeeded",
                        "error_call_count": len(error_calls),
                    },
                )
            if len(successful_calls) > 1:
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={
                        "reason": "survey-create succeeded multiple times",
                        "successful_call_count": len(successful_calls),
                        "inputs": [call.input for call in successful_calls],
                    },
                )
            return Score(
                name=self._name(),
                score=1.0,
                metadata={
                    "survey_id": _extract_survey_id(successful_calls[-1]),
                    "error_call_count": len(error_calls),
                },
            )

        if successful_calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "survey-create succeeded but this case expected an error",
                    "input": successful_calls[-1].input,
                },
            )
        if not error_calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Expected a survey-create error but no errored call was observed"},
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"error_call_count": len(error_calls), "input": error_calls[-1].input},
        )


class SurveyCreateReturnedId(Scorer):
    """Binary: did a successful survey-create result include an extractable survey ID?"""

    def _name(self) -> str:
        return "survey_create_returned_id"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> Score:
        spec = _expected_spec(expected, "survey_created") or {}
        if spec.get("should_create", True) is not True:
            return Score(name=self._name(), score=None, metadata={"reason": "Survey ID not expected"})

        call = _last_survey_create_call(output, successful=True)
        if call is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No successful survey-create call"})

        survey_id = _extract_survey_id(call)
        if not survey_id:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Could not extract survey ID from tool output"},
            )
        return Score(name=self._name(), score=1.0, metadata={"survey_id": survey_id})


class SurveyIdInFinalMessage(Scorer):
    """Binary: does the final assistant message include the created survey ID?"""

    def _name(self) -> str:
        return "survey_id_in_final_message"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> Score:
        spec = _expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No ID-in-final-message expectation"})
        if spec.get("required", True) is not True:
            return Score(name=self._name(), score=None, metadata={"reason": "ID-in-final-message not required"})

        call = _last_survey_create_call(output, successful=True)
        if call is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No successful survey-create call"})

        survey_id = _extract_survey_id(call)
        if not survey_id:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Could not extract survey ID from tool output"},
            )

        last_message = output.get("last_message") if output else ""
        if not isinstance(last_message, str):
            last_message = str(last_message)
        if survey_id in last_message:
            return Score(name=self._name(), score=1.0, metadata={"survey_id": survey_id})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "Survey ID missing from final message", "survey_id": survey_id},
        )


class SurveyCreateRejected(Scorer):
    """Binary: did the agent attempt survey-create and receive a validation failure?"""

    def _name(self) -> str:
        return "survey_create_rejected"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> Score:
        spec = _expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No rejection expectation"})

        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = parser.get_tool_calls(SURVEY_CREATE_TOOL_NAME)
        if not calls:
            return Score(name=self._name(), score=0.0, metadata={"reason": "survey-create was never attempted"})

        successful = [call for call in calls if not _survey_create_experienced_error(call)]
        if successful:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "survey-create succeeded for an invalid survey", "input": successful[-1].input},
            )

        error_calls = [call for call in calls if _survey_create_experienced_error(call)]
        last_call = error_calls[-1] if error_calls else calls[-1]
        expected_questions = spec.get("questions")
        if expected_questions is not None and last_call.input.get("questions") != expected_questions:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "survey-create was attempted with different questions than expected",
                    "expected_questions": expected_questions,
                    "actual_questions": last_call.input.get("questions"),
                },
            )

        if _survey_create_experienced_error(last_call):
            return Score(name=self._name(), score=1.0, metadata={"input": last_call.input})

        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "survey-create did not surface a validation failure", "output": last_call.output[:500]},
        )


class SurveyCreateSchemaAlignment(_JudgedScorer):
    """Graded score: how well does the actual survey-create input match the expected survey?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_survey_create_input(output)
        if actual is None:
            spec = _expected_spec(expected, "survey_create_alignment")
            if spec is None:
                return Score(
                    name=self._name(),
                    score=None,
                    metadata={"reason": "No survey-create alignment expectation"},
                )
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran survey-create successfully"},
            )

        expected_survey, reason = _materialize_expected_survey(expected, output)
        if expected_survey is None:
            return Score(name=self._name(), score=None, metadata={"reason": reason})

        return {
            "output": {"survey": actual, "prompt": _user_prompt(output)},
            "expected": {"survey": expected_survey},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="survey_create_alignment",
            prompt_template="""
You are judging whether an agent-produced PostHog `survey-create` MCP payload would create the survey the user asked for, compared to a reference expected survey.

The bar is semantic equivalence, not strict field equality. Accept harmless defaults and equivalent wording, but reject material differences that would create a different survey.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Material aspects:
1. **Name and description**: The survey name should match the user request. Description may be omitted only when it was not material to the prompt.
2. **Survey type**: `popover` is the default for in-app surveys. `widget`, `api`, or `external_survey` must be used when the prompt asks for that type.
3. **Launch state**: If expected has `should_launch: true`, the actual payload must include a non-null `start_date`. If expected has `should_launch: false`, the actual payload must not set `start_date`.
4. **Questions**: Count, order, question text, and required fields must align. NPS should be a `rating` question with `scale: 10` and numeric display. CSAT should be a `rating` question with `scale: 5`. Open questions should be `open`. PMF-style choices should be `single_choice`. Multiple-select questions should be `multiple_choice`.
5. **Choice lists and labels**: Choice values, lower/upper rating labels, optional status, links, and button text are material when present in the expected survey.
6. **Feature flag targeting**: `linked_flag_id` must match the expected ID. For variant targeting, `conditions.linkedFlagVariant` must match the expected variant.
7. **URL/display conditions**: URL conditions must match the requested path and match type. Treat `contains` and `icontains` as equivalent for a "contains" URL request.

Ignore:
- `appearance`, `enable_partial_responses`, `schedule`, generated question IDs, `_posthogUrl`, analytics metadata, and other sensible defaults unless the prompt made them material.
- Minor wording differences in question text that preserve the same respondent-facing meaning.

Penalize:
- Creating extra questions not requested by the user.
- Launching a survey that was meant to stay draft, or failing to launch one the user explicitly asked to launch.
- Missing targeting, wrong feature flag, wrong variant, wrong URL condition, wrong question type, or wrong rating scale.

<expected_survey>
{{expected.survey}}
</expected_survey>

<actual_payload>
{{output.survey}}
</actual_payload>
""".strip()
            + "\n\n"
            + GRADED_ALIGNMENT_RUBRIC,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )
