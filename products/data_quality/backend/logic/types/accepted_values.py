import json

from pydantic import Field, field_validator

from posthog.hogql import ast

from ...facade.enums import CheckType
from ..contracts import CheckPlan, SubjectRef
from ..errors import CheckConfigError
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


_NUMERIC_PREFIXES = ("Int", "UInt", "Float", "Decimal")


def _coerce_value(value: str | float | bool, column_type: str) -> str | float | bool:
    """One accepted value in the column's own type, or unchanged when the column holds strings."""
    if column_type.startswith("Bool"):
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in ("true", "false"):
            return lowered == "true"
        raise CheckConfigError(f"{value!r} is not a true/false value, but the column is {column_type}.")
    if column_type.startswith(_NUMERIC_PREFIXES):
        if isinstance(value, bool):
            raise CheckConfigError(f"{value!r} is not a number, but the column is {column_type}.")
        try:
            return float(value)
        except (TypeError, ValueError):
            raise CheckConfigError(f"{value!r} is not a number, but the column is {column_type}.")
    return value


class AcceptedValuesSpec(CheckTypeSpec):
    type_name = CheckType.ACCEPTED_VALUES
    config_model = AcceptedValuesConfig
    requires_column = True
    description = "Fails on rows whose column value is outside the allowed set. Nulls are ignored."

    def coerce_to_column(self, config: CheckConfig, column_type: str | None) -> CheckConfig:
        """Read the accepted values as the column reads them.

        The editor's value control can only produce strings, so a numeric or boolean column would
        otherwise be compared against strings -- and "1" would fingerprint differently from the 1 an
        agent sends for the same check. Left alone when the column type is unknown.
        """
        assert isinstance(config, AcceptedValuesConfig)
        if not column_type:
            return config
        bare = column_type[len("Nullable(") : -1] if column_type.startswith("Nullable(") else column_type
        return AcceptedValuesConfig(values=[_coerce_value(value, bare) for value in config.values])

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
