"""Experiment scorers for sandboxed agent evals.

These scorers grade the world-facing artifact produced through PostHog MCP:
the successful ``experiment-create`` tool result and the final assistant
message. They intentionally avoid Max harness state such as graph nodes or
``AssistantState``.
"""

from __future__ import annotations

import re
import json
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser, ToolCall

EXPERIMENT_CREATE_TOOL_NAME = "experiment-create"
EXPERIMENT_GET_TOOL_NAME = "experiment-get"
EXPERIMENT_LAUNCH_TOOL_NAME = "experiment-launch"
EXPERIMENT_UPDATE_TOOL_NAME = "experiment-update"
FEATURE_FLAG_CREATE_TOOL_NAME = "create-feature-flag"

_ID_BOUNDARY_TEMPLATE = r"(?<!\d){experiment_id}(?!\d)"


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
