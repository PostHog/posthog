from typing import Self

from pydantic import Field, model_validator

from posthog.hogql import ast

from ...facade.enums import CheckType
from ..contracts import CheckPlan, Evaluation, SubjectRef
from ..spec import CheckConfig, CheckTypeSpec
from .common import one, subject_source

ROW_COUNT_ALIAS = "row_count"


class RowCountConfig(CheckConfig):
    min: int | None = Field(default=None, ge=0, description="Fail if the table has fewer rows than this.")
    max: int | None = Field(default=None, ge=0, description="Fail if the table has more rows than this.")

    @model_validator(mode="after")
    def _bounds_are_usable(self) -> Self:
        if self.min is None and self.max is None:
            raise ValueError("needs at least one of min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"needs min <= max, got min={self.min} and max={self.max}")
        return self


class RowCountSpec(CheckTypeSpec):
    """The one type that does not use zero-failing-rows semantics: it compares a count to bounds."""

    type_name = CheckType.ROW_COUNT
    config_model = RowCountConfig
    requires_column = False
    description = "Fails when the table's row count falls outside min/max. At least one bound is required."

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        return CheckPlan(
            failing_rows=ast.SelectQuery(select=[one()], select_from=subject_source(subject)),
            # No row is individually at fault here, so the diagnostic is the number the bounds were
            # compared against rather than a projection of every row in the table.
            diagnostic_rows=ast.SelectQuery(
                select=[ast.Alias(alias=ROW_COUNT_ALIAS, expr=ast.Call(name="count", args=[]))],
                select_from=subject_source(subject),
            ),
            failed_count_expr=None,
            observed_value_expr=ast.Call(name="count", args=[]),
            evaluation=Evaluation.BOUNDS,
        )


SPEC = RowCountSpec()
