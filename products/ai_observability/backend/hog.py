from typing import Any, Literal

from rest_framework import serializers

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_program

from products.cdp.backend.validation import compile_hog

AIObservabilityHogType = Literal["destination", "tagger"]


def compile_ai_observability_hog(source: str, hog_type: AIObservabilityHogType) -> list[Any]:
    return compile_hog(source, hog_type, null_safe_comparisons=True)


def _detail_text(detail: Any) -> str:
    if isinstance(detail, dict):
        return " ".join(_detail_text(value) for value in detail.values())
    if isinstance(detail, list):
        return " ".join(_detail_text(value) for value in detail)
    return str(detail)


def hog_compile_error_message(source: str, error: Exception) -> str:
    """Why `source` failed to compile, in words a person can act on.

    `compile_hog` reports a syntax error as "Hog code has errors." and drops where it is, so the source is
    parsed again here to name the line.
    """
    try:
        parse_program(source)
    except ExposedHogQLError as syntax_error:
        if syntax_error.start is None:
            return f"Compilation error: {syntax_error}"
        line = source.count("\n", 0, syntax_error.start) + 1
        return f"Compilation error on line {line}: {syntax_error}"
    if isinstance(error, serializers.ValidationError):
        return f"Compilation error: {_detail_text(error.detail)}"
    return f"Compilation error: {error}"
