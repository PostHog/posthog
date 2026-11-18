from typing import Literal
from uuid import UUID

from pydantic import Field

from posthog.hogql import ast

from ...facade.enums import CheckType, SubjectType
from ..contracts import CheckPlan, SubjectRef
from ..errors import CheckConfigError, SubjectUnresolvableError
from ..spec import CheckConfig, CheckTypeSpec
from .common import column, diagnostic_of, narrowed_to, one, subject_source, window_expr


class RelationshipsConfig(CheckConfig):
    to_subject_type: Literal[SubjectType.TABLE, SubjectType.VIEW, SubjectType.POSTHOG_TABLE] = Field(
        description="Kind of object holding the referenced values."
    )
    to_subject_uuid: UUID = Field(description="Id of the table, view or PostHog table holding the referenced values.")
    to_column: str = Field(min_length=1, description="Column holding the referenced values.")
    to_lookback_hours: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Only look for a match among the referenced subject's rows from the last N hours. "
            "Optional, and only for a referenced subject with a time column."
        ),
    )


class RelationshipsSpec(CheckTypeSpec):
    """Referential integrity: every non-null value must exist in another subject's column."""

    type_name = CheckType.RELATIONSHIPS
    config_model = RelationshipsConfig
    requires_column = True
    description = "Fails on rows whose column value has no match in the referenced subject's column."

    def related_subject_ref(self, config: CheckConfig) -> tuple[str, str] | None:
        assert isinstance(config, RelationshipsConfig)
        return str(config.to_subject_type), str(config.to_subject_uuid)

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        assert isinstance(config, RelationshipsConfig)
        if related is None or not related.exists:
            raise SubjectUnresolvableError(
                f"The referenced {config.to_subject_type} {config.to_subject_uuid} no longer resolves."
            )
        if config.to_lookback_hours is not None and not related.time_column:
            raise CheckConfigError(
                f"The referenced {config.to_subject_type} has no time column, "
                "so it cannot take a to_lookback_hours window."
            )
        value = column(column_name)
        referenced = narrowed_to(
            ast.SelectQuery(select=[column(config.to_column)], select_from=subject_source(related)),
            window_expr(related.time_column, config.to_lookback_hours),
        )
        failing_rows = ast.SelectQuery(
            select=[one()],
            select_from=subject_source(subject),
            where=ast.And(
                exprs=[
                    ast.Call(name="isNotNull", args=[value]),
                    ast.CompareOperation(left=value, op=ast.CompareOperationOp.NotIn, right=referenced),
                ]
            ),
        )
        return CheckPlan(failing_rows=failing_rows, diagnostic_rows=diagnostic_of(failing_rows))


SPEC = RelationshipsSpec()
