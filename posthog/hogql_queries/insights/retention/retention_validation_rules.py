from rest_framework.exceptions import ValidationError

from posthog.schema import EntityType, RetentionQuery

from posthog.hogql_queries.insights.utils.breakdowns import has_breakdown_filter
from posthog.hogql_queries.validation.validation import QueryValidationContext


class DisallowCumulativeWith24HourWindows:
    code = "retention_cumulative_24_hour_windows_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        if retention_filter.timeWindowMode == "24_hour_windows" and retention_filter.cumulative:
            raise ValidationError("Cumulative retention is not supported for 24 hour windows.", code=self.code)


class DisallowBreakdownsWithDataWarehouse24HourWindows:
    """The 24-hour-window builder resolves a data warehouse series without an events scan in its outer query,
    so breakdown expressions (which read events / person columns) have nothing to resolve against."""

    code = "retention_data_warehouse_24_hour_windows_breakdowns_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        if retention_filter.timeWindowMode != "24_hour_windows":
            return
        if not has_breakdown_filter(context.query.breakdownFilter):
            return
        has_data_warehouse_series = any(
            entity is not None and entity.type == EntityType.DATA_WAREHOUSE
            for entity in (retention_filter.targetEntity, retention_filter.returningEntity)
        )
        if has_data_warehouse_series:
            raise ValidationError(
                "Breakdowns are not supported for 24 hour windows with a data warehouse series.",
                code=self.code,
            )
