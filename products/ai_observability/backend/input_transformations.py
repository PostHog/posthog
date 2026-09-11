from collections.abc import Iterable
from typing import NotRequired, Protocol, TypedDict

import re2


class EvaluationInputTransformation(TypedDict):
    pattern: str
    replacement: NotRequired[str]


class _CompiledPattern(Protocol):
    def sub(self, replacement: str, text: str, count: int = 0) -> str: ...


CompiledInputTransformations = tuple[tuple[_CompiledPattern, str], ...]


def compile_input_transformations(
    transformations: Iterable[EvaluationInputTransformation],
) -> CompiledInputTransformations:
    compiled: list[tuple[_CompiledPattern, str]] = []
    for transformation in transformations:
        try:
            pattern = re2.compile(transformation["pattern"])
        except re2.error as error:
            raise ValueError(f"Invalid regular expression: {error}") from error
        replacement = transformation.get("replacement", "").replace("\\", "\\\\")
        compiled.append((pattern, replacement))
    return tuple(compiled)


def apply_input_transformations(content: str, transformations: CompiledInputTransformations) -> str:
    for pattern, replacement in transformations:
        content = pattern.sub(replacement, content)
    return content
