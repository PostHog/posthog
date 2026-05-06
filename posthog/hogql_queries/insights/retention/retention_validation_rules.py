from rest_framework.exceptions import ValidationError

from posthog.schema import RetentionQuery

from posthog.hogql_queries.validation.validation import QueryValidationContext


class DisallowCumulativeWith24HourWindows:
    code = "retention_cumulative_24_hour_windows_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        if retention_filter.timeWindowMode == "24_hour_windows" and retention_filter.cumulative:
            raise ValidationError("Cumulative retention is not supported for 24 hour windows.", code=self.code)
