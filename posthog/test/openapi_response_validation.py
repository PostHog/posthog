from __future__ import annotations

import os
import re
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from django.http import HttpResponse

from drf_spectacular.generators import SchemaGenerator
from jsonschema import ValidationError
from jsonschema.validators import Draft7Validator, RefResolver

_JSON_CONTENT_TYPES: tuple[str, ...] = ("application/json", "application/problem+json")


@dataclass
class OpenAPIValidationEvent:
    event: str
    method: str
    path: str
    status_code: int
    reason: str
    details: str | None = None


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
            )
        )

    def write_machine_readable_report(self, output_path: str) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.events:
            counts[item.reason] = counts.get(item.reason, 0) + 1

        report: dict[str, Any] = {
            "events": [asdict(item) for item in self.events],
            "summary": {
                "total": len(self.events),
                "by_reason": counts,
            },
        }

        with open(output_path, "w", encoding="utf-8") as file_handle:
            json.dump(report, file_handle, sort_keys=True)
            file_handle.write("\n")

        return report


class OpenAPIResponseValidator:
    def __init__(self, schema: dict[str, Any], recorder: OpenAPIValidationRecorder, strict: bool = False) -> None:
        self.schema = schema
        self.recorder = recorder
        self.strict = strict
        self._compiled_paths = self._compile_paths(schema.get("paths", {}))
        self._resolver = RefResolver.from_schema(schema)

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
                reason="path_not_in_schema",
            )
            return

        operation = path_item.get(method.lower())
        if not isinstance(operation, dict):
            self.recorder.record(
                event="skip",
                method=method,
                path=path,
                status_code=status_code,
                reason="method_not_in_schema",
            )
            return

        response_schema = self._get_response_schema(operation, status_code)
        if response_schema is None:
            self.recorder.record(
                event="skip",
                method=method,
                path=path,
                status_code=status_code,
                reason="response_schema_not_declared",
            )
            return

        if self._is_empty_response(response):
            self.recorder.record(
                event="validated",
                method=method,
                path=path,
                status_code=status_code,
                reason="empty_body",
            )
            return

        if not self._is_json_response(response):
            self.recorder.record(
                event="skip",
                method=method,
                path=path,
                status_code=status_code,
                reason="non_json_response",
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
                reason="invalid_json_body",
                details=message,
            )
            if self.strict:
                raise AssertionError(
                    self._failure_json(method, path, status_code, "invalid_json_body", message)
                ) from error
            return

        try:
            self._validate_payload(payload, response_schema)
        except ValidationError as error:
            message = self._format_validation_error(error)
            self.recorder.record(
                event="failed",
                method=method,
                path=path,
                status_code=status_code,
                reason="schema_validation_failed",
                details=message,
            )
            if self.strict:
                raise AssertionError(
                    self._failure_json(method, path, status_code, "schema_validation_failed", message)
                ) from error
            return

        self.recorder.record(
            event="validated",
            method=method,
            path=path,
            status_code=status_code,
            reason="schema_validation_passed",
        )

    def _validate_payload(self, payload: Any, schema: dict[str, Any]) -> None:
        if schema.get("nullable") and payload is None:
            return

        normalized_schema = self._normalize_nullable(schema)
        validator = Draft7Validator(normalized_schema, resolver=self._resolver)
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
        for pattern, path_item in self._compiled_paths:
            if pattern.match(path):
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
    def _get_response_schema(operation: dict[str, Any], status_code: int) -> dict[str, Any] | None:
        responses = operation.get("responses")
        if not isinstance(responses, dict):
            return None

        response_obj = responses.get(str(status_code)) or responses.get("default")
        if not isinstance(response_obj, dict):
            return None

        content = response_obj.get("content")
        if not isinstance(content, dict):
            return None

        media_type = content.get("application/json") or content.get("application/problem+json")
        if not isinstance(media_type, dict):
            return None

        schema = media_type.get("schema")
        if not isinstance(schema, dict):
            return None

        return schema

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
    schema = SchemaGenerator().get_schema(request=None, public=True)
    if schema is None:
        raise RuntimeError("OpenAPI schema generation returned None")

    recorder = OpenAPIValidationRecorder()
    strict = os.getenv("OPENAPI_RESPONSE_VALIDATION_STRICT", "").lower() in {"1", "true", "yes"}
    return OpenAPIResponseValidator(schema=schema, recorder=recorder, strict=strict)
