from posthog.hogql import ast

from ...facade.enums import CheckType
from ..contracts import CheckPlan, SubjectRef
from ..spec import CheckConfig, CheckTypeSpec, NoConfig
from .common import column, subject_source


class UniqueSpec(CheckTypeSpec):
    type_name = CheckType.UNIQUE
    config_model = NoConfig
    requires_column = True
    description = "Fails once per column value that appears more than once. Nulls are ignored."

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        value = column(column_name)
        return CheckPlan(
            failing_rows=ast.SelectQuery(
                select=[value],
                select_from=subject_source(subject),
                where=ast.Call(name="isNotNull", args=[value]),
                group_by=[value],
                having=ast.CompareOperation(
                    left=ast.Call(name="count", args=[]),
                    op=ast.CompareOperationOp.Gt,
                    right=ast.Constant(value=1),
                ),
            )
        )


SPEC = UniqueSpec()
