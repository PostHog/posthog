import json

from pydantic import Field, field_validator

from posthog.hogql import ast

from ...facade.enums import CheckType
from ..contracts import CheckPlan, SubjectRef
from ..spec import CheckConfig, CheckTypeSpec
from .common import column, diagnostic_of, one, subject_source


class AcceptedValuesConfig(CheckConfig):
    values: list[str | float | bool] = Field(
        min_length=1, description="The complete set of values the column is allowed to take."
    )

    @field_validator("values")
    @classmethod
    def _canonical_set(cls, values: list[str | float | bool]) -> list[str | float | bool]:
        # values is semantically a set: dedupe and order deterministically (by JSON representation,
        # which totally orders across the mixed value types) so two configs differing only in
        # ordering or repetition normalize identically and upsert instead of creating a twin.
        by_repr = {json.dumps(value, sort_keys=True): value for value in values}
        return [by_repr[key] for key in sorted(by_repr)]


class AcceptedValuesSpec(CheckTypeSpec):
    type_name = CheckType.ACCEPTED_VALUES
    config_model = AcceptedValuesConfig
    requires_column = True
    description = "Fails on rows whose column value is outside the allowed set. Nulls are ignored."

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        assert isinstance(config, AcceptedValuesConfig)
        value = column(column_name)
        failing_rows = ast.SelectQuery(
            select=[one()],
            select_from=subject_source(subject),
            where=ast.And(
                exprs=[
                    ast.Call(name="isNotNull", args=[value]),
                    ast.CompareOperation(
                        left=value,
                        op=ast.CompareOperationOp.NotIn,
                        right=ast.Constant(value=list(config.values)),
                    ),
                ]
            ),
        )
        return CheckPlan(failing_rows=failing_rows, diagnostic_rows=diagnostic_of(failing_rows))


SPEC = AcceptedValuesSpec()
