from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen

TRINO_COMPILER_VERSION = 1


class TrinoExpansionMode(StrEnum):
    PURE = "pure"
    DJANGO = "django"


@frozen
class TrinoDiagnostic:
    code: str
    message: str
    start: int | None = None
    end: int | None = None


@frozen
class TrinoColumn:
    name: str
    type: str


@frozen
class TrinoCompilation:
    sql: str
    values: dict[str, Any] = field(repr=False)
    hogql: str | None = None
    print_columns: tuple[str, ...] = ()
    output_columns: tuple[TrinoColumn, ...] = ()
    dependencies: tuple[str, ...] = ()
    fingerprint: str = ""
    warnings: tuple[TrinoDiagnostic, ...] = ()
