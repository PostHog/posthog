from rest_framework.exceptions import ValidationError

from posthog.schema import StickinessOperator, StickinessQuery

from posthog.hogql_queries.validation.validation import QueryValidationContext

MAX_INTERVAL_COUNT = 365
STICKINESS_CRITERIA_NEGATIVE_CODE = "stickiness_criteria_negative"
STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE = "stickiness_criteria_zero_incompatible"
STICKINESS_INTERVAL_COUNT_NON_POSITIVE_CODE = "stickiness_interval_count_non_positive"
STICKINESS_INTERVAL_COUNT_TOO_LARGE_CODE = "stickiness_interval_count_too_large"


class ValidateStickinessCriteria:
    code = STICKINESS_CRITERIA_NEGATIVE_CODE

    def validate(self, context: QueryValidationContext[StickinessQuery]) -> None:
        criteria = context.query.stickinessFilter.stickinessCriteria if context.query.stickinessFilter else None
        if criteria is None:
            return

        if criteria.value < 0:
            raise ValidationError(
                "Stickiness criteria value must be non-negative.", code=STICKINESS_CRITERIA_NEGATIVE_CODE
            )

        if criteria.value == 0 and criteria.operator in (StickinessOperator.EXACT, StickinessOperator.LTE):
            raise ValidationError(
                "Stickiness criteria with operator exact or lte must use a value greater than 0.",
                code=STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE,
            )


class ValidateIntervalCount:
    code = STICKINESS_INTERVAL_COUNT_NON_POSITIVE_CODE

    def validate(self, context: QueryValidationContext[StickinessQuery]) -> None:
        interval_count = context.query.intervalCount
        if interval_count is None:
            return

        if interval_count <= 0:
            raise ValidationError(
                "intervalCount must be a positive integer.", code=STICKINESS_INTERVAL_COUNT_NON_POSITIVE_CODE
            )

        if interval_count > MAX_INTERVAL_COUNT:
            raise ValidationError(
                f"intervalCount cannot exceed {MAX_INTERVAL_COUNT}.",
                code=STICKINESS_INTERVAL_COUNT_TOO_LARGE_CODE,
            )
