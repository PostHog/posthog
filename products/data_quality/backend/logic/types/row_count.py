from pydantic import Field

from posthog.hogql import ast

from ...facade.enums import CheckType
from ..contracts import CheckPlan, Evaluation, SubjectRef
from ..spec import CheckConfig, CheckTypeSpec
from .common import BoundsConfig, one, subject_source

ROW_COUNT_ALIAS = "row_count"


class RowCountConfig(BoundsConfig):
    # A row count is a whole number and never negative, so its bounds are too, and the published
    # config schema has to say so for an API or agent caller that has no other contract to read.
    # Narrowed here rather than on BoundsConfig, so a bounds check over a measured value can still
    # take a fractional one. The inherited normalizer still folds an integral float to an int.
    min: int | None = Field(default=None, ge=0, description="Fail if the table has fewer rows than this.")
    max: int | None = Field(default=None, ge=0, description="Fail if the table has more rows than this.")


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
