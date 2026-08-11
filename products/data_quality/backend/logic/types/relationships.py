from uuid import UUID

from pydantic import Field

from posthog.hogql import ast

from ...facade.enums import CheckType, SubjectType
from ..contracts import CheckPlan, SubjectRef
from ..errors import SubjectUnresolvableError
from ..spec import CheckConfig, CheckTypeSpec
from .common import column, diagnostic_of, one, subject_source


class RelationshipsConfig(CheckConfig):
    to_subject_type: SubjectType = Field(description="Kind of catalog object holding the referenced values.")
    to_subject_uuid: UUID = Field(description="Id of the table or view holding the referenced values.")
    to_column: str = Field(min_length=1, description="Column holding the referenced values.")


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
        value = column(column_name)
        referenced = ast.SelectQuery(
            select=[column(config.to_column)],
            select_from=subject_source(related),
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
