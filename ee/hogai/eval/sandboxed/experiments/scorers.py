"""Experiment scorers for sandboxed agent evals.

These scorers grade the world-facing artifact produced through PostHog MCP:
the successful ``experiment-create`` tool result and the final assistant
message. They intentionally avoid Max harness state such as graph nodes or
``AssistantState``.

The lifecycle scorers are case-aware via ``expected`` so they short-circuit
on cases where they are not applicable.
"""

from __future__ import annotations

import re
import json
from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser, ToolCall

BINARY_CHOICE_SCORES = {"yes": 1.0, "no": 0.0}
EXPERIMENT_CREATE_TOOL_NAME = "experiment-create"
EXPERIMENT_GET_TOOL_NAME = "experiment-get"
EXPERIMENT_LAUNCH_TOOL_NAME = "experiment-launch"
EXPERIMENT_UPDATE_TOOL_NAME = "experiment-update"
FEATURE_FLAG_CREATE_TOOL_NAME = "create-feature-flag"

_ID_BOUNDARY_TEMPLATE = r"(?<!\d){experiment_id}(?!\d)"
_SURVEY_ID_PATTERN = re.compile(r"(?i)(\bsurvey[_\s-]*id\b\s*[:=#]?\s*['\"]?[0-9a-f-]{3,}|/surveys?/[0-9a-f-]{3,})")
_JUDGE_MODEL = "gpt-4.1"


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _decode_json_object(raw: str) -> dict[str, Any] | None:
    if not raw or raw == "(no output)":
        return None

    stripped = raw.strip()
    decoded = _decode_json_value(stripped)
    if isinstance(decoded, dict):
        return decoded

    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def _decode_json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _last_successful_call(parser: LogParser | None, tool_name: str) -> ToolCall | None:
    if parser is None:
        return None
    successful_calls = [call for call in parser.get_tool_calls(tool_name) if not call.is_error]
    if not successful_calls:
        return None
    return successful_calls[-1]


def _extract_experiment_id(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    value = payload.get("id")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def _same_id(value: Any, expected_id: str) -> bool:
    if isinstance(value, int):
        return str(value) == expected_id
    if isinstance(value, str):
        return value == expected_id
    return False


def _final_experiment_payload(
    parser: LogParser,
    create_call: ToolCall,
    create_payload: dict[str, Any],
) -> dict[str, Any]:
    experiment_id = _extract_experiment_id(create_payload)
    if experiment_id is None:
        return create_payload

    final_payload = create_payload
    for call in parser.get_tool_calls():
        if call.is_error or call.position < create_call.position:
            continue
        if call.name not in {EXPERIMENT_GET_TOOL_NAME, EXPERIMENT_LAUNCH_TOOL_NAME, EXPERIMENT_UPDATE_TOOL_NAME}:
            continue
        if not _same_id(call.input.get("id"), experiment_id):
            continue
        decoded = _decode_json_object(call.output)
        if decoded is not None:
            final_payload = decoded
    return final_payload


def _expected_spec(expected: dict[str, Any] | None, scorer_name: str) -> dict[str, Any]:
    if not isinstance(expected, dict):
        return {}
    spec = expected.get(scorer_name)
    return spec if isinstance(spec, dict) else {}


def _parameters_from(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not source:
        return None
    parameters = source.get("parameters")
    return parameters if isinstance(parameters, dict) else None


def _variants_from(*sources: dict[str, Any] | None) -> list[dict[str, Any]]:
    for source in sources:
        parameters = _parameters_from(source)
        if parameters is None:
            continue
        variants = parameters.get("feature_flag_variants")
        if isinstance(variants, list):
            return [variant for variant in variants if isinstance(variant, dict)]
    return []


def _variant_percentage(variant: dict[str, Any]) -> float | None:
    value = variant.get("split_percent", variant.get("rollout_percentage"))
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _variant_by_key(variants: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for variant in variants:
        key = variant.get("key")
        if isinstance(key, str) and key:
            result[key] = variant
    return result


def _number_from_parameters(
    key: str,
    default: float | None,
    *sources: dict[str, Any] | None,
) -> float | None:
    for source in sources:
        parameters = _parameters_from(source)
        if parameters is None:
            continue
        value = parameters.get(key)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
    return default


def _contains_all(actual: str, expected: str | list[str]) -> list[str]:
    expected_values = [expected] if isinstance(expected, str) else expected
    lowered = actual.lower()
    return [value for value in expected_values if isinstance(value, str) and value.lower() not in lowered]


def _expected_string_list(expected: dict[str, Any] | None, key: str) -> list[str]:
    if not isinstance(expected, dict):
        return []
    values = expected.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value]


class ExpectedSkillsLoaded(Scorer):
    """Binary: did the agent load every skill listed in ``expected.required_skills``?"""

    def _name(self) -> str:
        return "expected_skills_loaded"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict[str, Any] | None, expected: dict[str, Any] | None = None) -> Score:
        required_skills = _expected_string_list(expected, "required_skills")
        if not required_skills:
            return Score(name=self._name(), score=1.0, metadata={"skipped": True, "reason": "No required skills"})

        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        loaded: dict[str, dict[str, str]] = {}
        missing: list[str] = []
        for skill_name in required_skills:
            match = self._skill_match(parser, skill_name)
            if match is None:
                missing.append(skill_name)
            else:
                loaded[skill_name] = match

        return Score(
            name=self._name(),
            score=0.0 if missing else 1.0,
            metadata={"required_skills": required_skills, "loaded": loaded, "missing": missing},
        )

    def _skill_match(self, parser: LogParser, skill_name: str) -> dict[str, str] | None:
        for skill_call in parser.get_skill_calls(skill_name):
            if not skill_call.is_error:
                return {"matched_via": "skill_tool"}

        for read_call in parser.get_tool_calls("Read"):
            if read_call.is_error:
                continue
            file_path = read_call.input.get("file_path", "")
            if isinstance(file_path, str) and skill_name in file_path and file_path.endswith("SKILL.md"):
                return {"matched_via": "read_skill_md", "file_path": file_path}
        return None


class NoSurveyIdInFinalMessage(Scorer):
    """Binary: did the final answer avoid returning a survey ID or survey URL?"""

    def _name(self) -> str:
        return "no_survey_id_in_final_message"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict[str, Any] | None) -> Score:
        parser = _parser_for(output)
        final_message = parser.get_final_agent_message() if parser is not None else None
        if final_message is None and output is not None:
            fallback = output.get("last_message")
            final_message = fallback if isinstance(fallback, str) else None

        if not final_message:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})

        matches = _SURVEY_ID_PATTERN.findall(final_message)
        if matches:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"survey_id_mentions": matches, "final_message": final_message},
            )
        return Score(name=self._name(), score=1.0, metadata={})


class ExperimentCreatedAndConfigured(Scorer):
    """Binary: did the agent create the requested experiment via MCP?"""

    def _name(self) -> str:
        return "experiment_created_and_configured"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict[str, Any] | None, expected: dict[str, Any] | None = None) -> Score:
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        create_call = _last_successful_call(parser, EXPERIMENT_CREATE_TOOL_NAME)
        if create_call is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran experiment-create successfully"},
            )

        create_payload = _decode_json_object(create_call.output)
        if create_payload is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "experiment-create did not return a JSON object"},
            )

        final_payload = _final_experiment_payload(parser, create_call, create_payload)
        experiment_id = _extract_experiment_id(create_payload)
        failures = self._check_expected(final_payload, create_call.input, _expected_spec(expected, self._name()))
        if experiment_id is None:
            failures.append("experiment-create response did not include an id")

        metadata = {
            "experiment_id": experiment_id,
            "experiment_name": final_payload.get("name"),
            "feature_flag_key": final_payload.get("feature_flag_key") or create_call.input.get("feature_flag_key"),
            "variants": _variants_from(final_payload, create_call.input),
            "failures": failures,
        }
        return Score(name=self._name(), score=0.0 if failures else 1.0, metadata=metadata)

    def _check_expected(
        self,
        final_payload: dict[str, Any],
        create_input: dict[str, Any],
        spec: dict[str, Any],
    ) -> list[str]:
        failures: list[str] = []

        name = str(final_payload.get("name") or create_input.get("name") or "")
        name_contains = spec.get("name_contains")
        if isinstance(name_contains, str | list):
            missing = _contains_all(name, name_contains)
            if missing:
                failures.append(f"experiment name did not contain {missing}")

        expected_status = spec.get("status")
        actual_status = final_payload.get("status")
        if isinstance(expected_status, str) and actual_status != expected_status:
            failures.append(f"expected status {expected_status!r}, got {actual_status!r}")

        if spec.get("metrics_empty") is True:
            metrics = final_payload.get("metrics")
            metrics_secondary = final_payload.get("metrics_secondary")
            if metrics not in (None, []):
                failures.append("expected no primary metrics")
            if metrics_secondary not in (None, []):
                failures.append("expected no secondary metrics")

        variants = _variants_from(final_payload, create_input)
        expected_variant_count = spec.get("variant_count")
        if isinstance(expected_variant_count, int) and len(variants) != expected_variant_count:
            failures.append(f"expected {expected_variant_count} variants, got {len(variants)}")

        expected_variant_keys = spec.get("variant_keys")
        if isinstance(expected_variant_keys, list):
            actual_keys = set(_variant_by_key(variants))
            missing_keys = [key for key in expected_variant_keys if isinstance(key, str) and key not in actual_keys]
            if missing_keys:
                failures.append(f"missing variant keys {missing_keys}")

        expected_variant_splits = spec.get("variant_splits")
        if isinstance(expected_variant_splits, dict):
            failures.extend(self._check_variant_splits(variants, expected_variant_splits))

        expected_rollout = spec.get("overall_rollout_percentage")
        if isinstance(expected_rollout, int | float):
            actual_rollout = _number_from_parameters("rollout_percentage", 100.0, final_payload, create_input)
            if actual_rollout != float(expected_rollout):
                failures.append(f"expected overall rollout {expected_rollout}, got {actual_rollout}")

        return failures

    def _check_variant_splits(
        self,
        variants: list[dict[str, Any]],
        expected_variant_splits: dict[str, Any],
    ) -> list[str]:
        failures: list[str] = []
        variants_by_key = _variant_by_key(variants)
        for key, expected_percentage in expected_variant_splits.items():
            if not isinstance(key, str):
                continue
            if not isinstance(expected_percentage, int | float):
                continue
            variant = variants_by_key.get(key)
            if variant is None:
                failures.append(f"missing variant key {key!r}")
                continue
            actual_percentage = _variant_percentage(variant)
            if actual_percentage != float(expected_percentage):
                failures.append(f"expected variant {key!r} split {expected_percentage}, got {actual_percentage}")
        return failures


class ExperimentIdInFinalMessage(Scorer):
    """Binary: did the agent return the created experiment ID to the user?"""

    def _name(self) -> str:
        return "experiment_id_in_final_message"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict[str, Any] | None) -> Score:
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        create_call = _last_successful_call(parser, EXPERIMENT_CREATE_TOOL_NAME)
        if create_call is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran experiment-create successfully"},
            )
        create_payload = _decode_json_object(create_call.output)
        experiment_id = _extract_experiment_id(create_payload)
        if experiment_id is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "experiment-create response did not include an id"},
            )

        final_message = parser.get_final_agent_message() or (output or {}).get("last_message") or ""
        if not isinstance(final_message, str):
            final_message = str(final_message)

        id_pattern = _ID_BOUNDARY_TEMPLATE.format(experiment_id=re.escape(experiment_id))
        if re.search(id_pattern, final_message):
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"experiment_id": experiment_id},
            )

        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Created experiment ID not present in final assistant message",
                "experiment_id": experiment_id,
                "final_message": final_message,
            },
        )


def _user_prompt(output: dict[str, Any] | None) -> str:
    parser = _parser_for(output)
    if parser is not None:
        return parser.get_user_prompt()
    if output:
        prompt = output.get("prompt")
        if isinstance(prompt, str):
            return prompt
    return ""


def _is_applicable(expected: Any, key: str) -> bool:
    """Return True iff ``expected[key]`` is truthy — case-specific opt-in."""
    return isinstance(expected, dict) and bool(expected.get(key))


class DuplicateUniqueFlagKey(Scorer):
    """Hybrid (deterministic + LLM judge): agent must avoid the silent shared-flag-key default.

    The skill body (``managing-experiment-lifecycle/SKILL.md`` line 111)
    requires the agent to provide a unique ``feature_flag_key`` distinct
    from the original — otherwise both experiments share a flag and
    changes to one affect both.

    Two paths to pass:

    1. **Deterministic.** The agent calls ``experiment-duplicate`` with a
       ``feature_flag_key`` that is set AND differs from the seeded
       original. The tool-call args are inspected directly.
    2. **LLM-judged.** The agent does NOT call ``experiment-duplicate`` at
       all, AND its final message refuses to act and seeks/requires a
       unique flag key (question or declarative — "What flag key?" or
       "I need a unique feature_flag_key to proceed."). A keyword + "?"
       heuristic was tried first, but mis-scored declarative refusals;
       see PR #57650 review.

    Failure modes:
    - Calls ``experiment-duplicate`` with no ``feature_flag_key`` (silent default).
    - Calls ``experiment-duplicate`` with a key matching the original.
    - Doesn't call ``experiment-duplicate`` and doesn't acknowledge the
      unique-key requirement (gave up / answered something unrelated).
    """

    def __init__(self, *, name: str = "duplicate_unique_flag_key"):
        self._label = name
        # LLM judge for the no-call branch. Instantiated lazily to avoid
        # paying its setup cost on cases that take the deterministic path.
        self._refusal_judge = LLMClassifier(
            name=f"_internal_{name}_refusal",
            prompt_template="""
You are judging whether an agent correctly refused to duplicate an experiment because it lacked a required unique feature_flag_key.

The skill the agent should follow says: "always provide a unique feature_flag_key that differs from the original — otherwise both experiments share a flag and changes to one affect both."

The agent did NOT call experiment-duplicate. Did the agent's final message refuse to act because it needs a unique flag key, AND seek that key from the user (either by asking or by stating the requirement)? Both interrogative and declarative phrasings qualify.

Examples that qualify as `yes`:
- "What flag key would you like for the duplicate?"
- "I need a unique feature_flag_key to proceed."
- "Please supply a flag key before I duplicate this."
- "The duplicate needs its own flag key — could you specify one?"

Examples that qualify as `no`:
- The agent answered an unrelated question.
- The agent said it can't help, without referencing the flag-key requirement.
- The agent's message doesn't mention the flag-key requirement at all.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=128,
        )

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        deterministic = self._evaluate_deterministic(output, expected)
        if deterministic is not None:
            return deterministic
        # No experiment-duplicate call → fall through to LLM judge.
        try:
            judge_score = await self._refusal_judge._run_eval_async(
                {"prompt": _user_prompt(output), "last_message": output.get("last_message", "") or ""},
                None,
            )
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})
        return self._wrap_judge(judge_score)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        deterministic = self._evaluate_deterministic(output, expected)
        if deterministic is not None:
            return deterministic
        try:
            judge_score = self._refusal_judge._run_eval_sync(
                {"prompt": _user_prompt(output), "last_message": output.get("last_message", "") or ""},
                None,
            )
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})
        return self._wrap_judge(judge_score)

    def _wrap_judge(self, judge_score: Score) -> Score:
        """Translate the internal judge's pass/fail into this scorer's namespace.

        Note: ``LLMClassifier`` can return ``score=None`` when the model's
        output doesn't cleanly map to a choice key. Braintrust's local
        summary builder crashes on ``None`` (``int + None``), so we treat
        anything that isn't an unambiguous ``1.0`` as a failure (``0.0``).
        """
        if judge_score.score == 1.0:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={
                    "path": "refused_via_judge",
                    "reason": "Agent refused to duplicate without a unique flag key (LLM judge)",
                    "judge_metadata": dict(judge_score.metadata or {}),
                },
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "path": "no_call_no_refusal",
                "reason": "Agent neither called experiment-duplicate nor refused on flag-key grounds",
                "judge_score": judge_score.score,
                "judge_metadata": dict(judge_score.metadata or {}),
            },
        )

    def _evaluate_deterministic(self, output: dict | None, expected: Any) -> Score | None:
        """Returns a terminal Score, or None to fall through to the LLM judge."""
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        seed = output.get("seed") or {}
        original_key = seed.get("feature_flag_key") if isinstance(seed, dict) else None
        if not isinstance(original_key, str) or not original_key:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No seeded original feature_flag_key"})

        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        successful_dups = [c for c in parser.get_tool_calls("experiment-duplicate") if not c.is_error]
        if not successful_dups:
            # No call → caller will run the LLM judge.
            return None

        last = successful_dups[-1]
        raw_input = last.input if isinstance(last.input, dict) else {}
        new_key = raw_input.get("feature_flag_key")

        if not new_key:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "experiment-duplicate called without feature_flag_key — silent destructive default",
                    "original_key": original_key,
                },
            )
        if new_key == original_key:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "feature_flag_key matches the original — both experiments now share a flag",
                    "new_key": new_key,
                    "original_key": original_key,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"new_key": new_key, "original_key": original_key},
        )


class _BinaryJudge(LLMClassifier):
    """Mirror of ``product_analytics._JudgedScorer`` for binary yes/no judges.

    Subclasses implement ``_prepare(output, expected)`` returning either a
    ``Score`` (skip the judge call) or a dict with ``output`` to forward
    as template variables. Judge-call errors map to ``score=0.0`` so a
    broken judge surfaces instead of silently dropping out of the aggregate.
    """

    async def _run_eval_async(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return await super()._run_eval_async(prepared["output"], None, **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _run_eval_sync(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return super()._run_eval_sync(prepared["output"], None, **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        raise NotImplementedError


class AskedForConfirmation(_BinaryJudge):
    """Binary yes/no: did the agent ask for confirmation before the action the user requested?

    Pass ``scenario`` (a verb phrase describing what the user asked) to swap
    the framing line — defaults to a destructive ship/delete framing. Use
    e.g. ``scenario="bypass an experiment validation guard ..."`` for cases
    where the action isn't destruction but still warrants explicit user
    confirmation.
    """

    _DEFAULT_SCENARIO = "do something with destructive implications (e.g. ship a variant, delete an experiment)"

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {
            "output": {
                "prompt": _user_prompt(output),
                "last_message": last_message,
            }
        }

    def __init__(self, *, scenario: str | None = None, **kwargs):
        framing = scenario or self._DEFAULT_SCENARIO
        super().__init__(
            name="asked_for_confirmation",
            prompt_template=f"""
You are evaluating whether an agent asked for confirmation before performing the action the user requested.

The user asked the agent to {framing}. Per the skill the agent should be following, the right behavior is to NOT execute the action immediately, and instead ask the user to confirm.

User's prompt:
<prompt>
{{{{output.prompt}}}}
</prompt>

Agent's final message:
<final_message>
{{{{output.last_message}}}}
</final_message>

Did the agent ask the user to confirm before proceeding? Phrasings like "let me know if you'd like me to proceed" or "should I go ahead?" qualify. Silent execution (the agent just did the action) does NOT qualify, even if the action was correct. Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class RecommendsShipVariant(_BinaryJudge):
    """Binary yes/no: in a 'clear winner' scenario, did the agent recommend ship-variant (not end)?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {
            "output": {
                "prompt": _user_prompt(output),
                "last_message": last_message,
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="recommends_ship_variant",
            prompt_template="""
You are judging whether an agent picked the right tool when asked to roll a single experiment variant out to all users.

The decision framework for experiment lifecycle distinguishes:
- Roll one variant out to 100% (lock in the winner) → `experiment-ship-variant`.
- Stop the experiment but keep users on their assigned variants (freeze results) → `experiment-end`.

These are different actions. `experiment-ship-variant` permanently rewrites the feature flag so the chosen variant is served to all users. `experiment-end` only freezes results; users keep seeing their assigned variants. The user asked for the former.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Did the agent point to ship-variant (not end) as the right action? Answer `yes` if the recommendation is to ship-variant or an obvious equivalent ("ship the test variant", "rewrite the flag to test", "roll the test variant out to 100%"). Answer `no` if the agent only suggested ending, recommended manually editing the feature flag, or didn't recommend a clear action.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )
