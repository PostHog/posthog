from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from posthog.test.openapi_response_validation import OpenAPIResponseValidator, OpenAPIValidationRecorder


@dataclass
class _FakeRequest:
    method: str
    path: str


@dataclass
class _FakeResponse:
    wsgi_request: _FakeRequest
    status_code: int
    headers: dict[str, str]
    content: bytes
    charset: str = "utf-8"


@pytest.fixture
def base_schema() -> dict:
    return {
        "openapi": "3.0.3",
        "paths": {
            "/api/projects/{team_id}/widgets/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "name": {"type": "string"},
                                        },
                                        "required": ["id", "name"],
                                        "additionalProperties": False,
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {},
    }


def test_validates_dynamic_openapi_paths(base_schema: dict) -> None:
    recorder = OpenAPIValidationRecorder()
    validator = OpenAPIResponseValidator(base_schema, recorder)

    response = _FakeResponse(
        wsgi_request=_FakeRequest(method="GET", path="/api/projects/123/widgets/"),
        status_code=200,
        headers={"Content-Type": "application/json"},
        content=json.dumps({"id": 1, "name": "Widget"}).encode("utf-8"),
    )

    validator.validate_response(response)

    assert recorder.events[-1].reason == "schema_validation_passed"


def test_raises_machine_readable_error_on_schema_mismatch(base_schema: dict) -> None:
    recorder = OpenAPIValidationRecorder()
    validator = OpenAPIResponseValidator(base_schema, recorder)

    response = _FakeResponse(
        wsgi_request=_FakeRequest(method="GET", path="/api/projects/123/widgets/"),
        status_code=200,
        headers={"Content-Type": "application/json"},
        content=json.dumps({"id": "not-an-integer", "name": "Widget"}).encode("utf-8"),
    )

    with pytest.raises(AssertionError, match='"reason": "schema_validation_failed"'):
        validator.validate_response(response)


def test_nullable_schema_is_supported() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {
            "/api/projects/{team_id}/widgets/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "optional_name": {"type": "string", "nullable": True},
                                        },
                                        "required": ["optional_name"],
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    recorder = OpenAPIValidationRecorder()
    validator = OpenAPIResponseValidator(schema, recorder)

    response = _FakeResponse(
        wsgi_request=_FakeRequest(method="GET", path="/api/projects/1/widgets/"),
        status_code=200,
        headers={"Content-Type": "application/json"},
        content=json.dumps({"optional_name": None}).encode("utf-8"),
    )

    validator.validate_response(response)

    assert recorder.events[-1].reason == "schema_validation_passed"
