from posthog.hogql import ast

from ...facade.enums import CheckType
from ..contracts import CheckPlan, SubjectRef
from ..spec import CheckConfig, CheckTypeSpec, NoConfig
from .common import column, diagnostic_of, one, subject_source


class NotNullSpec(CheckTypeSpec):
    type_name = CheckType.NOT_NULL
    config_model = NoConfig
    requires_column = True
    description = "Fails on rows where the column is null."

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        failing_rows = ast.SelectQuery(
            select=[one()],
            select_from=subject_source(subject),
            where=ast.Call(name="isNull", args=[column(column_name)]),
        )
        return CheckPlan(failing_rows=failing_rows, diagnostic_rows=diagnostic_of(failing_rows))


SPEC = NotNullSpec()
