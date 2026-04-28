from __future__ import annotations

import os
import re
import json
import contextvars
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from django.http import HttpResponse

from drf_spectacular.generators import SchemaGenerator
from jsonschema import ValidationError
from jsonschema.validators import Draft7Validator, RefResolver

_JSON_CONTENT_TYPES: tuple[str, ...] = ("application/json", "application/problem+json")


# Reason codes use a 4-tier prefix taxonomy so related entries group naturally when the report
# is sorted alphabetically and so a glance at the prefix tells you what kind of finding it is:
#
#   validated_*  — response was checked against the spec and passed (or had nothing to check).
#   failed_*     — response was checked and diverged from the spec. Highest signal: real bug.
#   gap_*        — the spec was missing something we'd have needed to validate. Actionable on
#                  the viewset/serializer side (annotate the response, declare the status, etc.).
#   unmatched_*  — couldn't connect the request to anything in the spec at all. Lowest signal —
#                  often a validator-side limitation (path pattern, content type) rather than a
#                  real defect.
#
# Priority drives summary ordering: higher = more interesting. Within a tier we still order by
# count so the largest bucket inside the tier surfaces first.
_REASON_PRIORITY: dict[str, int] = {
    # failed_* — real divergence between response and spec.
    "failed_nullability": 100,
    "failed_type": 100,
    "failed_missing_required": 100,
    "failed_unexpected_property": 100,
    "failed_enum": 100,
    "failed_polymorphic": 100,
    "failed_format": 100,
    "failed_other": 100,
    "failed_invalid_json": 100,
    # validated_* — checked successfully.
    "validated": 60,
    "validated_empty_body": 60,
    # gap_* — spec annotation gap. Status-class-specific buckets so a missing 2xx (response
    # shape we actually return) doesn't drown in the noise of missing 4xx error annotations.
    "gap_status_2xx": 50,
    "gap_no_responses": 40,
    "gap_no_schema": 40,
    "gap_no_json_media": 40,
    "gap_status_5xx": 35,
    "gap_status_3xx": 25,
    "gap_status_4xx": 15,
    # unmatched_* — couldn't even connect the request to the spec.
    "unmatched_non_json": 10,
    "unmatched_method": 5,
    "unmatched_path": 0,
}


# Set by the conftest fixture before each test runs so events captured during the test can be
# attributed back to a specific pytest node id (e.g. ``ee/.../test_x.py::TestY::test_z``).
# A ContextVar is used so concurrent tests under pytest-xdist or anyio-style fixtures don't
# leak each other's IDs.
_current_test_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "openapi_validation_test_id", default=None
)


def set_current_test_id(test_id: str | None) -> None:
    """Set (or clear) the pytest node id attached to subsequent validation events."""
    _current_test_id.set(test_id)


@dataclass
class OpenAPIValidationEvent:
    event: str
    method: str
    path: str
    status_code: int
    reason: str
    details: str | None = None
    test_id: str | None = None


class OpenAPIValidationRecorder:
    def __init__(self) -> None:
        self.events: list[OpenAPIValidationEvent] = []

    def record(
        self,
        *,
        event: str,
        method: str,
        path: str,
        status_code: int,
        reason: str,
        details: str | None = None,
    ) -> None:
        self.events.append(
            OpenAPIValidationEvent(
                event=event,
                method=method,
                path=path,
                status_code=status_code,
                reason=reason,
                details=details,
                test_id=_current_test_id.get(),
            )
        )

    def write_machine_readable_report(self, output_path: str) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.events:
            counts[item.reason] = counts.get(item.reason, 0) + 1

        # Sort by descending priority (real bugs first), then descending count, then name.
        # Coverage gaps like ``unmatched_path`` end up at the bottom by design — when we
        # ran out of ways to match a request to the spec, that's the least interesting bucket.
        ordered_counts = dict(
            sorted(
                counts.items(),
                key=lambda kv: (-_REASON_PRIORITY.get(kv[0], 0), -kv[1], kv[0]),
            )
        )

        report: dict[str, Any] = {
            "events": [asdict(item) for item in self.events],
            "summary": {
                "total": len(self.events),
                "by_reason": ordered_counts,
            },
        }

        # ``sort_keys=False`` to preserve the priority ordering above.
        with open(output_path, "w", encoding="utf-8") as file_handle:
            json.dump(report, file_handle, sort_keys=False)
            file_handle.write("\n")

        return report


class OpenAPIResponseValidator:
    def __init__(self, schema: dict[str, Any], recorder: OpenAPIValidationRecorder, strict: bool = False) -> None:
        # Normalize OpenAPI 3.0's `nullable: true` into JSON Schema `type: [..., "null"]`
        # across the entire spec — including component schemas reached via $ref. Doing this
        # once up front avoids reasoning about ref resolution per-request.
        self.schema = self._normalize_nullable(schema)
        self.recorder = recorder
        self.strict = strict
        self._compiled_paths = self._compile_paths(self.schema.get("paths", {}))
        self._resolver = RefResolver.from_schema(self.schema)

    def validate_response(self, response: HttpResponse) -> None:
        request = getattr(response, "wsgi_request", None)
        if request is None:
            return

        method = request.method.upper()
        path = request.path
        status_code = response.status_code

        if not path.startswith("/api/"):
            return

        if path == "/api/schema/":
            return

        path_item = self._find_path_item(path)
        if path_item is None:
            self.recorder.record(
                event="skip",
                method=method,
                path=path,
                status_code=status_code,
                reason="unmatched_path",
            )
            return

        operation = path_item.get(method.lower())
        if not isinstance(operation, dict):
            self.recorder.record(
                event="skip",
                method=method,
                path=path,
                status_code=status_code,
                reason="unmatched_method",
            )
            return

        response_schema, missing_reason = self._get_response_schema(operation, status_code)
        if response_schema is None:
            assert missing_reason is not None
            if missing_reason == "gap_status":
                missing_reason = self._classify_status_gap(status_code)
            self.recorder.record(
                event="skip",
                method=method,
                path=path,
                status_code=status_code,
                reason=missing_reason,
            )
            return

        if self._is_empty_response(response):
            self.recorder.record(
                event="validated",
                method=method,
                path=path,
                status_code=status_code,
                reason="validated_empty_body",
            )
            return

        if not self._is_json_response(response):
            self.recorder.record(
                event="skip",
                method=method,
                path=path,
                status_code=status_code,
                reason="unmatched_non_json",
            )
            return

        try:
            payload = json.loads(response.content.decode(response.charset or "utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            message = f"unable to decode JSON body: {error}"
            self.recorder.record(
                event="failed",
                method=method,
                path=path,
                status_code=status_code,
                reason="failed_invalid_json",
                details=message,
            )
            if self.strict:
                raise AssertionError(
                    self._failure_json(method, path, status_code, "failed_invalid_json", message)
                ) from error
            return

        try:
            self._validate_payload(payload, response_schema)
        except ValidationError as error:
            reason = self._classify_validation_error(error)
            message = self._format_validation_error(error)
            self.recorder.record(
                event="failed",
                method=method,
                path=path,
                status_code=status_code,
                reason=reason,
                details=message,
            )
            if self.strict:
                raise AssertionError(self._failure_json(method, path, status_code, reason, message)) from error
            return

        self.recorder.record(
            event="validated",
            method=method,
            path=path,
            status_code=status_code,
            reason="validated",
        )

    def _validate_payload(self, payload: Any, schema: dict[str, Any]) -> None:
        # Schema (including any $ref targets) was already normalized at construction time.
        validator = Draft7Validator(schema, resolver=self._resolver)
        validator.validate(payload)

    @staticmethod
    def _normalize_nullable(schema: Any) -> Any:
        if isinstance(schema, list):
            return [OpenAPIResponseValidator._normalize_nullable(item) for item in schema]

        if not isinstance(schema, dict):
            return schema

        transformed: dict[str, Any] = {k: OpenAPIResponseValidator._normalize_nullable(v) for k, v in schema.items()}
        nullable = transformed.pop("nullable", False)

        if nullable is True:
            if "$ref" in transformed:
                return {"anyOf": [transformed, {"type": "null"}]}

            existing_type = transformed.get("type")
            if isinstance(existing_type, str):
                transformed["type"] = [existing_type, "null"]
            elif isinstance(existing_type, list) and "null" not in existing_type:
                transformed["type"] = [*existing_type, "null"]
            else:
                transformed = {"anyOf": [transformed, {"type": "null"}]}

        return transformed

    @staticmethod
    def _compile_paths(paths: dict[str, Any]) -> list[tuple[re.Pattern[str], dict[str, Any]]]:
        compiled: list[tuple[re.Pattern[str], dict[str, Any]]] = []
        for openapi_path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            pattern = re.sub(r"\{[^/]+\}", r"[^/]+", openapi_path)
            compiled.append((re.compile(f"^{pattern}$"), path_item))

        return compiled

    def _find_path_item(self, path: str) -> dict[str, Any] | None:
        # Try the path as-is, then with/without a trailing slash. Test traffic frequently
        # drops the trailing slash that drf-spectacular emits in the spec.
        candidates = [path]
        if path.endswith("/"):
            candidates.append(path.rstrip("/"))
        else:
            candidates.append(path + "/")

        for candidate in candidates:
            for pattern, path_item in self._compiled_paths:
                if pattern.match(candidate):
                    return path_item
        return None

    @staticmethod
    def _is_json_response(response: HttpResponse) -> bool:
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        return content_type in _JSON_CONTENT_TYPES

    @staticmethod
    def _is_empty_response(response: HttpResponse) -> bool:
        if response.status_code in {204, 304}:
            return True
        return response.content in (b"", None)

    @staticmethod
    def _get_response_schema(operation: dict[str, Any], status_code: int) -> tuple[dict[str, Any] | None, str | None]:
        """Return ``(schema, None)`` when found, otherwise ``(None, reason)`` so the caller
        can record a precise reason for why the spec didn't yield a schema. Each reason
        maps to a specific actionable fix:

        * ``gap_no_responses`` — operation has no ``responses`` key.
        * ``gap_status`` — status code (and ``default``) absent from ``responses``. The caller
          refines this into ``gap_status_2xx``/``3xx``/``4xx``/``5xx`` based on the status class.
        * ``gap_no_json_media`` — status declared, but no JSON media type for it.
        * ``gap_no_schema`` — JSON media type declared, but it has no ``schema``.
        """
        responses = operation.get("responses")
        if not isinstance(responses, dict):
            return None, "gap_no_responses"

        response_obj = responses.get(str(status_code)) or responses.get("default")
        if not isinstance(response_obj, dict):
            return None, "gap_status"

        content = response_obj.get("content")
        if not isinstance(content, dict):
            # No content key — usually means operation declares an empty body for this status.
            return None, "gap_no_json_media"

        # Use explicit membership checks: an empty dict ``{}`` declared for the media type is
        # truthy presence but falsy under ``or``, which would silently misclassify the case.
        for content_type in _JSON_CONTENT_TYPES:
            if content_type in content:
                media_type = content[content_type]
                break
        else:
            return None, "gap_no_json_media"

        if not isinstance(media_type, dict):
            return None, "gap_no_json_media"

        schema = media_type.get("schema")
        if not isinstance(schema, dict):
            return None, "gap_no_schema"

        return schema, None

    @staticmethod
    def _classify_status_gap(status_code: int) -> str:
        """Pick a status-class-specific bucket so a 2xx gap (real undocumented response
        shape) doesn't drown in the noise of 4xx gaps (error responses are routinely
        unannotated in drf-spectacular output).
        """
        if 200 <= status_code < 300:
            return "gap_status_2xx"
        if 300 <= status_code < 400:
            return "gap_status_3xx"
        if 400 <= status_code < 500:
            return "gap_status_4xx"
        if 500 <= status_code < 600:
            return "gap_status_5xx"
        return "gap_status"

    @staticmethod
    def _classify_validation_error(error: ValidationError) -> str:
        """Bucket ``jsonschema`` validation errors into actionable categories. The fallback
        ``failed_other`` covers anything that doesn't fit one of the known error shapes.
        """
        validator = error.validator
        if validator == "type":
            # ``None is not of type 'string'`` is the dominant case; the response field is
            # null but the spec didn't mark it nullable. Worth its own bucket because the
            # fix is mechanical (annotate ``allow_null=True`` / ``nullable: true``).
            if error.instance is None:
                return "failed_nullability"
            return "failed_type"
        if validator == "required":
            return "failed_missing_required"
        if validator == "additionalProperties":
            return "failed_unexpected_property"
        if validator == "enum":
            return "failed_enum"
        if validator in {"oneOf", "anyOf"}:
            # Polymorphic union: the response shape didn't match any declared variant.
            # Usually means the spec's union list is missing a variant the code returns.
            return "failed_polymorphic"
        if validator in {"format", "pattern", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}:
            # Value-level constraint failures (regex, range, length). Grouped because the
            # fix is "loosen the constraint" or "tighten the response", not annotation.
            return "failed_format"
        return "failed_other"

    @staticmethod
    def _format_validation_error(error: ValidationError) -> str:
        path_segments = [str(segment) for segment in error.path]
        error_path = ".".join(path_segments) if path_segments else "$"
        return f"path={error_path}; message={error.message}"

    @staticmethod
    def _failure_json(method: str, path: str, status_code: int, reason: str, details: str) -> str:
        return json.dumps(
            {
                "event": "failed",
                "method": method,
                "path": path,
                "status_code": status_code,
                "reason": reason,
                "details": details,
            },
            sort_keys=True,
        )


@lru_cache(maxsize=1)
def build_openapi_response_validator() -> OpenAPIResponseValidator:
    # Include INTERNAL-scoped endpoints in the spec so we can validate test traffic that
    # hits them. Mirrors the flags used by `hogli build:openapi-schema` — the mock secret
    # lets schema generation walk views that require InternalAPIAuthentication.
    os.environ.setdefault("OPENAPI_INCLUDE_INTERNAL", "1")
    os.environ.setdefault("OPENAPI_MOCK_INTERNAL_API_SECRET", "1")

    schema = SchemaGenerator().get_schema(request=None, public=True)
    if schema is None:
        raise RuntimeError("OpenAPI schema generation returned None")

    recorder = OpenAPIValidationRecorder()
    strict = os.getenv("OPENAPI_RESPONSE_VALIDATION_STRICT", "").lower() in {"1", "true", "yes"}
    return OpenAPIResponseValidator(schema=schema, recorder=recorder, strict=strict)
