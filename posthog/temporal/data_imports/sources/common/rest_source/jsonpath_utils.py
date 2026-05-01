from typing import Any, Union

from jsonpath_ng import JSONPath
from jsonpath_ng.ext import parse as jsonpath_parse

TJsonPath = Union[str, JSONPath]


def compile_path(path: TJsonPath) -> JSONPath:
    if isinstance(path, JSONPath):
        return path
    return jsonpath_parse(path)


def find_values(path: TJsonPath, data: dict[str, Any]) -> list[Any]:
    compiled = compile_path(path)
    return [match.value for match in compiled.find(data)]
