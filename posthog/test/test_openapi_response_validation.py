from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from posthog.test.openapi_response_validation import (
    OpenAPIResponseValidator,
    OpenAPIValidationRecorder,
    set_current_test_id,
)


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

    assert recorder.events[-1].reason == "validated"


def test_records_schema_mismatch_without_failing_in_default_mode(base_schema: dict) -> None:
    recorder = OpenAPIValidationRecorder()
    validator = OpenAPIResponseValidator(base_schema, recorder)

    response = _FakeResponse(
        wsgi_request=_FakeRequest(method="GET", path="/api/projects/123/widgets/"),
        status_code=200,
        headers={"Content-Type": "application/json"},
        content=json.dumps({"id": "not-an-integer", "name": "Widget"}).encode("utf-8"),
    )

    validator.validate_response(response)
    assert recorder.events[-1].reason == "failed_type"


def test_raises_machine_readable_error_on_schema_mismatch_in_strict_mode(base_schema: dict) -> None:
    recorder = OpenAPIValidationRecorder()
    validator = OpenAPIResponseValidator(base_schema, recorder, strict=True)

    response = _FakeResponse(
        wsgi_request=_FakeRequest(method="GET", path="/api/projects/123/widgets/"),
        status_code=200,
        headers={"Content-Type": "application/json"},
        content=json.dumps({"id": "not-an-integer", "name": "Widget"}).encode("utf-8"),
    )

    with pytest.raises(AssertionError, match='"reason": "failed_type"'):
        validator.validate_response(response)


def _build_validator(schema: dict) -> tuple[OpenAPIResponseValidator, OpenAPIValidationRecorder]:
    recorder = OpenAPIValidationRecorder()
    return OpenAPIResponseValidator(schema, recorder), recorder


def _response(method: str, path: str, status_code: int, body: object) -> _FakeResponse:
    return _FakeResponse(
        wsgi_request=_FakeRequest(method=method, path=path),
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        content=json.dumps(body).encode("utf-8"),
    )


def test_classifies_nullability_mismatch_distinctly_from_type_mismatch(base_schema: dict) -> None:
    validator, recorder = _build_validator(base_schema)

    validator.validate_response(_response("GET", "/api/projects/1/widgets/", 200, {"id": None, "name": "Widget"}))

    assert recorder.events[-1].reason == "failed_nullability"


def test_classifies_missing_required_field(base_schema: dict) -> None:
    validator, recorder = _build_validator(base_schema)

    validator.validate_response(_response("GET", "/api/projects/1/widgets/", 200, {"id": 1}))

    assert recorder.events[-1].reason == "failed_missing_required"


def test_classifies_unexpected_property(base_schema: dict) -> None:
    validator, recorder = _build_validator(base_schema)

    validator.validate_response(
        _response("GET", "/api/projects/1/widgets/", 200, {"id": 1, "name": "Widget", "extra": True})
    )

    assert recorder.events[-1].reason == "failed_unexpected_property"


def test_event_records_current_test_id(base_schema: dict) -> None:
    validator, recorder = _build_validator(base_schema)

    set_current_test_id("path/to/test.py::TestSomething::test_case")
    try:
        validator.validate_response(_response("GET", "/api/projects/1/widgets/", 200, {"id": 1, "name": "W"}))
    finally:
        set_current_test_id(None)

    assert recorder.events[-1].test_id == "path/to/test.py::TestSomething::test_case"


def test_classifies_polymorphic_mismatch() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {
            "/api/widgets/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "oneOf": [
                                            {"type": "object", "properties": {"kind": {"const": "a"}}},
                                            {"type": "object", "properties": {"kind": {"const": "b"}}},
                                        ]
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    validator, recorder = _build_validator(schema)

    validator.validate_response(_response("GET", "/api/widgets/", 200, {"kind": "c"}))

    assert recorder.events[-1].reason == "failed_polymorphic"


def test_classifies_format_mismatch() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {
            "/api/widgets/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string", "maxLength": 3}},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    validator, recorder = _build_validator(schema)

    validator.validate_response(_response("GET", "/api/widgets/", 200, {"name": "too long"}))

    assert recorder.events[-1].reason == "failed_format"


def test_classifies_enum_mismatch() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {
            "/api/widgets/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"status": {"type": "string", "enum": ["a", "b"]}},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    validator, recorder = _build_validator(schema)

    validator.validate_response(_response("GET", "/api/widgets/", 200, {"status": "c"}))

    assert recorder.events[-1].reason == "failed_enum"


@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [
        (201, "gap_status_2xx"),
        (302, "gap_status_3xx"),
        (404, "gap_status_4xx"),
        (502, "gap_status_5xx"),
    ],
)
def test_status_class_skip_reasons(base_schema: dict, status_code: int, expected_reason: str) -> None:
    validator, recorder = _build_validator(base_schema)

    # base_schema only declares 200 — anything else falls into a status-class-specific bucket.
    validator.validate_response(_response("GET", "/api/projects/1/widgets/", status_code, {"detail": "x"}))

    assert recorder.events[-1].reason == expected_reason


def test_distinguishes_gap_no_json_media() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {
            "/api/widgets/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {"text/csv": {"schema": {"type": "string"}}},
                        }
                    }
                }
            }
        },
    }
    validator, recorder = _build_validator(schema)

    validator.validate_response(_response("GET", "/api/widgets/", 200, {"id": 1}))

    assert recorder.events[-1].reason == "gap_no_json_media"


def test_distinguishes_gap_no_schema() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {
            "/api/widgets/": {
                "get": {
                    "responses": {"200": {"content": {"application/json": {}}}},
                }
            }
        },
    }
    validator, recorder = _build_validator(schema)

    validator.validate_response(_response("GET", "/api/widgets/", 200, {"id": 1}))

    assert recorder.events[-1].reason == "gap_no_schema"


def test_gap_no_responses_when_no_responses_key() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {"/api/widgets/": {"get": {}}},
    }
    validator, recorder = _build_validator(schema)

    validator.validate_response(_response("GET", "/api/widgets/", 200, {"id": 1}))

    assert recorder.events[-1].reason == "gap_no_responses"


def test_nullable_inside_referenced_component_is_supported() -> None:
    schema = {
        "openapi": "3.0.3",
        "paths": {
            "/api/projects/{team_id}/widgets/": {
                "get": {
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Widget"}}}}
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Widget": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "nullable": True},
                    },
                    "required": ["start_date"],
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
        content=json.dumps({"start_date": None}).encode("utf-8"),
    )

    validator.validate_response(response)

    assert recorder.events[-1].reason == "validated"


def test_path_lookup_normalizes_trailing_slash(base_schema: dict) -> None:
    recorder = OpenAPIValidationRecorder()
    validator = OpenAPIResponseValidator(base_schema, recorder)

    response = _FakeResponse(
        wsgi_request=_FakeRequest(method="GET", path="/api/projects/123/widgets"),
        status_code=200,
        headers={"Content-Type": "application/json"},
        content=json.dumps({"id": 1, "name": "Widget"}).encode("utf-8"),
    )

    validator.validate_response(response)

    assert recorder.events[-1].reason == "validated"


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

    assert recorder.events[-1].reason == "validated"
