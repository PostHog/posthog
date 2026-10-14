import json
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.ai_observability.backend.models.offline_evaluations import OfflineEvaluationResult, OfflineExperiment
from products.ai_observability.backend.offline_evaluation_types import (
    ExperimentSubmission,
    ItemSubmission,
    JSONValue,
    ResultSubmission,
    ResultValue,
    UploadSubmission,
)

if TYPE_CHECKING:
    from rest_framework_dataclasses.types import Dataclass

MAX_UPLOAD_ITEMS = 1000
MAX_UPLOAD_RESULTS = 1000
MAX_ITEM_PAYLOAD_BYTES = 1024 * 1024
MAX_RESULT_PAYLOAD_BYTES = 256 * 1024
MAX_JSON_DEPTH = 32


class _StrictDataclassSerializer[T: Dataclass](DataclassSerializer[T]):
    def to_internal_value(self, data: object) -> T:
        if isinstance(data, Mapping):
            writable_fields = {name for name, field in self.fields.items() if not field.read_only}
            unsupported = set(data) - writable_fields
            if unsupported:
                raise serializers.ValidationError({str(name): ["This field is not supported."] for name in unsupported})
        return super().to_internal_value(cast(dict[str, object], data))


class _StrictCharField(serializers.CharField):
    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class _CountField(serializers.IntegerField):
    def to_internal_value(self, data: object) -> int:
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


class _UUIDField(serializers.UUIDField):
    def to_internal_value(self, data: object) -> UUID:
        if not isinstance(data, (str, UUID)):
            self.fail("invalid")
        return super().to_internal_value(data)


def _identifier_field(help_text: str, *, max_length: int = 255) -> _StrictCharField:
    return _StrictCharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        trim_whitespace=False,
        max_length=max_length,
        help_text=help_text,
    )


def _json_value_schema() -> dict[str, object]:
    return {
        "oneOf": [
            {"type": "object", "additionalProperties": True},
            {"type": "array", "items": {}},
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
        ]
    }


class _PayloadField(serializers.Field):
    allowed_keys: frozenset[str]
    string_keys: frozenset[str] = frozenset()
    max_bytes: int

    def _validate_json_values(self, data: dict[str, object]) -> None:
        pending: list[tuple[object, int]] = [(data, 1)]
        while pending:
            value, depth = pending.pop()
            if isinstance(value, (dict, list)):
                if depth > MAX_JSON_DEPTH:
                    raise serializers.ValidationError(f"JSON nesting must not exceed {MAX_JSON_DEPTH} levels.")
                if isinstance(value, dict):
                    if any(not isinstance(key, str) or "\x00" in key for key in value):
                        raise serializers.ValidationError("JSON object keys must be strings without null characters.")
                    pending.extend((child, depth + 1) for child in value.values())
                else:
                    pending.extend((child, depth + 1) for child in value)
            elif isinstance(value, str):
                if "\x00" in value:
                    raise serializers.ValidationError("JSON strings must not contain null characters.")
            elif value is not None and type(value) not in (bool, int, float):
                raise serializers.ValidationError("Provide valid JSON values.")

    def to_internal_value(self, data: object) -> dict[str, JSONValue]:
        if not isinstance(data, dict):
            raise serializers.ValidationError("Provide a JSON object.")
        unsupported = set(data) - self.allowed_keys
        if unsupported:
            raise serializers.ValidationError({str(key): ["This field is not supported."] for key in unsupported})
        if data.get("metadata") is not None and not isinstance(data["metadata"], dict):
            raise serializers.ValidationError({"metadata": ["Provide a JSON object or null."]})
        for key in self.string_keys:
            if data.get(key) is not None and not isinstance(data[key], str):
                raise serializers.ValidationError({key: ["Provide a string or null."]})

        self._validate_json_values(data)
        try:
            encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, UnicodeError) as error:
            raise serializers.ValidationError("Provide valid JSON with finite numbers and valid Unicode.") from error
        if len(encoded) > self.max_bytes:
            raise serializers.ValidationError(f"Payload must not exceed {self.max_bytes} bytes of UTF-8 JSON.")
        return cast(dict[str, JSONValue], data)

    def to_representation(self, value: dict[str, JSONValue]) -> dict[str, JSONValue]:
        return value


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "input": _json_value_schema(),
            "output": _json_value_schema(),
            "expected_output": _json_value_schema(),
            "metadata": {"type": "object", "additionalProperties": True, "nullable": True},
        },
    },
    component_name="OfflineExperimentItemPayloadInput",
)
class ItemPayloadField(_PayloadField):
    allowed_keys = frozenset({"input", "output", "expected_output", "metadata"})
    max_bytes = MAX_ITEM_PAYLOAD_BYTES


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reasoning": {"type": "string", "nullable": True},
            "error_message": {"type": "string", "nullable": True},
            "metadata": {"type": "object", "additionalProperties": True, "nullable": True},
        },
    },
    component_name="OfflineEvaluationResultPayloadInput",
)
class ResultPayloadField(_PayloadField):
    allowed_keys = frozenset({"reasoning", "error_message", "metadata"})
    string_keys = frozenset({"reasoning", "error_message"})
    max_bytes = MAX_RESULT_PAYLOAD_BYTES


@extend_schema_field(
    {
        "oneOf": [
            {"type": "number", "format": "double"},
            {"type": "boolean"},
            {"type": "array", "items": {"type": "string", "maxLength": 128}, "minItems": 1, "uniqueItems": True},
        ]
    }
)
class ResultValueField(serializers.Field):
    def to_internal_value(self, data: object) -> ResultValue:
        if isinstance(data, bool):
            return data
        if isinstance(data, (int, float)):
            try:
                value = float(data)
            except OverflowError as error:
                raise serializers.ValidationError("Provide a finite number.") from error
            if not math.isfinite(value):
                raise serializers.ValidationError("Provide a finite number.")
            return value
        if isinstance(data, list) and data:
            if any(not isinstance(value, str) or not value or len(value) > 128 for value in data):
                raise serializers.ValidationError("Category keys must be nonempty strings of at most 128 characters.")
            if any("\x00" in value or any("\ud800" <= character <= "\udfff" for character in value) for value in data):
                raise serializers.ValidationError("Category keys must contain valid Unicode without null characters.")
            if len(set(data)) != len(data):
                raise serializers.ValidationError("Category keys must be distinct.")
            return sorted(data)
        raise serializers.ValidationError("Provide a number, boolean, or nonempty array of category keys.")

    def to_representation(self, value: ResultValue) -> ResultValue:
        return value


class ExperimentSubmissionSerializer(_StrictDataclassSerializer[ExperimentSubmission]):
    id = _UUIDField(help_text="Caller-generated experiment UUID. Reuse it for exact retries.")
    name = _StrictCharField(max_length=400, help_text="Display name for this experiment execution.")
    started_at = serializers.DateTimeField(help_text="Execution start time in ISO 8601 format, supplied by the caller.")
    run_source = serializers.ChoiceField(
        choices=OfflineExperiment.RunSource.choices,
        required=False,
        allow_null=True,
        allow_blank=False,
        help_text="Where the execution started: ci, local, or scheduled. Omit or use null when unknown.",
    )
    expected_item_count = _CountField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=2**63 - 1,
        help_text="Expected number of distinct items. Completion must match this count when supplied.",
    )
    expected_result_count = _CountField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=2**63 - 1,
        help_text="Expected number of distinct item/scorer-version results, including non-success statuses.",
    )
    suite_key = _identifier_field("Stable identifier for comparing executions of the same evaluation suite.")
    dataset_source = _identifier_field(
        "Source of an external dataset. Hosted dataset provenance is derived from its revision."
    )
    dataset_identifier = _identifier_field("Stable identifier for the external dataset.")
    dataset_revision_identifier = _identifier_field("Pinned revision identifier of the external dataset.")
    dataset_revision_id = _UUIDField(
        required=False, allow_null=True, help_text="UUID of a hosted dataset revision in this project."
    )
    application_version = _identifier_field("Version of the application under evaluation.")
    model_version = _identifier_field("Version of the model under evaluation.")
    prompt_version = _identifier_field("Version of the prompt under evaluation.")

    class Meta:
        dataclass = ExperimentSubmission


class ItemSubmissionSerializer(_StrictDataclassSerializer[ItemSubmission]):
    id = _UUIDField(help_text="Caller-generated UUID for one input/output execution. Reuse for exact retries.")
    case_key = _identifier_field("Stable case identifier for matching inputs across experiments.")
    trial = _identifier_field("Identifier for a repeated execution of the same case.")
    dataset_item_identifier = _identifier_field("Stable item identifier in an external dataset.")
    dataset_item_version_identifier = _identifier_field("Pinned item-version identifier in an external dataset.")
    dataset_item_version_id = _UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of the hosted item version in the experiment's dataset revision.",
    )
    application_trace_id = _identifier_field(
        "Trace identifier for the application execution that produced this output."
    )
    payload = ItemPayloadField(
        required=False,
        help_text="Optional input/output payload, up to 1 MiB and 32 JSON levels. Omission, {} and null properties differ.",
    )

    class Meta:
        dataclass = ItemSubmission


class ResultSubmissionSerializer(_StrictDataclassSerializer[ResultSubmission]):
    item_id = _UUIDField(help_text="UUID of an item declared in this request or already accepted in this experiment.")
    scorer_version_id = _UUIDField(help_text="Exact UUID of an existing scorer version in this project.")
    status = serializers.ChoiceField(
        choices=OfflineEvaluationResult.Status.choices, help_text="Outcome of this scorer execution."
    )
    value = ResultValueField(
        required=False,
        allow_null=True,
        help_text="Required for ok: finite number, boolean, or distinct category keys matching the scorer version.",
    )
    error_code = _identifier_field("Optional stable error code, permitted only for error outcomes.", max_length=128)
    evaluator_trace_id = _identifier_field("Trace identifier of the evaluator that produced this result.")
    evaluated_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Caller-supplied evaluation time in ISO 8601 format."
    )
    payload = ResultPayloadField(
        required=False,
        help_text="Optional reasoning, error message, and metadata, up to 256 KiB and 32 JSON levels.",
    )

    class Meta:
        dataclass = ResultSubmission

    def validate(self, attrs: ResultSubmission) -> ResultSubmission:
        errors: dict[str, list[str] | dict[str, list[str]]] = {}
        if attrs.status == "ok" and attrs.value is None:
            errors["value"] = ["A score is required for an ok result."]
        if attrs.status != "ok" and attrs.value is not None:
            errors["value"] = ["Only an ok result may contain a score."]
        if attrs.status != "error" and attrs.error_code is not None:
            errors["error_code"] = ["Only an error result may contain an error code."]
        if attrs.status != "error" and attrs.payload and attrs.payload.get("error_message") is not None:
            errors["payload"] = {"error_message": ["Only an error result may contain an error message."]}
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class UploadSubmissionSerializer(_StrictDataclassSerializer[UploadSubmission]):
    items = serializers.ListField(
        child=ItemSubmissionSerializer(),
        required=False,
        max_length=MAX_UPLOAD_ITEMS,
        help_text="Complete immutable declarations for referenced items. Omit existing items to reuse them without a payload.",
    )
    results = serializers.ListField(
        child=ResultSubmissionSerializer(),
        allow_empty=False,
        min_length=1,
        max_length=MAX_UPLOAD_RESULTS,
        help_text="One to 1,000 unique item/scorer-version results. The entire request commits atomically.",
    )

    class Meta:
        dataclass = UploadSubmission

    def validate(self, attrs: UploadSubmission) -> UploadSubmission:
        item_ids: set[UUID] = set()
        item_errors: dict[str, dict[str, list[str]]] = {}
        referenced_ids = {result.item_id for result in attrs.results}
        for index, item in enumerate(attrs.items):
            if item.id in item_ids:
                item_errors[str(index)] = {"id": ["Each item may be declared only once per request."]}
            elif item.id not in referenced_ids:
                item_errors[str(index)] = {
                    "id": ["Every declared item must be referenced by a result in this request."]
                }
            item_ids.add(item.id)
        result_ids: set[tuple[UUID, UUID]] = set()
        result_errors: dict[str, dict[str, list[str]]] = {}
        for index, result in enumerate(attrs.results):
            identity = (result.item_id, result.scorer_version_id)
            if identity in result_ids:
                result_errors[str(index)] = {
                    "scorer_version_id": ["Each item/scorer-version pair may appear only once per request."]
                }
            result_ids.add(identity)
        errors = {}
        if item_errors:
            errors["items"] = item_errors
        if result_errors:
            errors["results"] = result_errors
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
