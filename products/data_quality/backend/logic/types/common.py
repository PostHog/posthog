"""Shared building blocks for check-type specs.

Every identifier reaching a query goes through a HogQL AST node, never string interpolation, so
the printer's backtick escaping is the only thing standing between a hostile column name and the
generated SQL.
"""

from math import isfinite
from typing import Self

from pydantic import Field, field_validator, model_validator

from posthog.hogql import ast

from ..contracts import SubjectRef
from ..spec import CheckConfig


class BoundsConfig(CheckConfig):
    min: int | float | None = Field(default=None, allow_inf_nan=False, description="Minimum allowed value, inclusive.")
    max: int | float | None = Field(default=None, allow_inf_nan=False, description="Maximum allowed value, inclusive.")

    @field_validator("min", "max")
    @classmethod
    def _normalize_integral_bounds(cls, value: int | float | None) -> int | float | None:
        return int(value) if isinstance(value, float) and value.is_integer() else value

    @model_validator(mode="after")
    def _bounds_are_usable(self) -> Self:
        if self.min is None and self.max is None:
            raise ValueError("needs at least one of min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"needs min <= max, got min={self.min} and max={self.max}")
        return self


def within_bounds(observed: float | None, minimum: float | None, maximum: float | None) -> bool:
    # NaN compares False against every bound, so an unguarded comparison reads it as passing.
    if observed is None or not isfinite(observed):
        return False
    if minimum is not None and observed < minimum:
        return False
    return not (maximum is not None and observed > maximum)


def subject_source(subject: SubjectRef) -> ast.JoinExpr:
    return ast.JoinExpr(table=ast.Field(chain=list(subject.queryable_name.split("."))))


def column(column_name: str) -> ast.Field:
    return ast.Field(chain=list(column_name.split(".")))


def one() -> ast.Constant:
    """Placeholder projection for subqueries whose rows matter but whose values do not."""
    return ast.Constant(value=1)


def star() -> ast.Field:
    """Projection for the diagnostic form, where the offending row is the whole point."""
    return ast.Field(chain=["*"])


def diagnostic_of(failing_rows: ast.SelectQuery) -> ast.SelectQuery:
    """The same rows the check counts, projected so a human can see what broke."""
    return ast.SelectQuery(select=[star()], select_from=failing_rows.select_from, where=failing_rows.where)
