from pydantic import Field

from posthog.hogql import ast

from ...facade.enums import CheckType
from ..contracts import CheckPlan, SubjectRef
from ..spec import CheckConfig, CheckTypeSpec
from .common import column, subject_source

STALENESS_ALIAS = "staleness_seconds"
SECONDS_PER_MINUTE = 60


class FreshnessConfig(CheckConfig):
    max_age_minutes: int = Field(
        ge=1, description="Fail when the newest value in the column is older than this many minutes."
    )


class FreshnessSpec(CheckTypeSpec):
    """How long ago the newest row landed.

    The inner query always returns exactly one row, so staleness is recorded as a time series even
    on a pass -- that series is what anomaly-detection check types will train on.
    """

    type_name = CheckType.FRESHNESS
    config_model = FreshnessConfig
    requires_column = True
    description = "Fails when the newest timestamp in the column is older than max_age_minutes."

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        assert isinstance(config, FreshnessConfig)
        staleness = ast.Field(chain=[STALENESS_ALIAS])
        threshold = ast.Constant(value=config.max_age_minutes * SECONDS_PER_MINUTE)
        return CheckPlan(
            failing_rows=ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias=STALENESS_ALIAS,
                        expr=ast.Call(
                            name="dateDiff",
                            args=[
                                ast.Constant(value="second"),
                                ast.Call(name="max", args=[column(column_name)]),
                                ast.Call(name="now", args=[]),
                            ],
                        ),
                    )
                ],
                select_from=subject_source(subject),
            ),
            # A null staleness means the column has no non-null value at all: an empty table, or a
            # pipeline that never wrote. That is exactly what freshness exists to catch, so it has to
            # count as a failure -- a bare `staleness > threshold` against null yields 0 and passes.
            failed_count_expr=ast.Call(
                name="countIf",
                args=[
                    ast.Or(
                        exprs=[
                            ast.Call(name="isNull", args=[staleness]),
                            ast.CompareOperation(left=staleness, op=ast.CompareOperationOp.Gt, right=threshold),
                        ]
                    )
                ],
            ),
            observed_value_expr=ast.Call(name="max", args=[staleness]),
        )


SPEC = FreshnessSpec()
