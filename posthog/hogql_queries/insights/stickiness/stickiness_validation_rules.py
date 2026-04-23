from rest_framework.exceptions import ValidationError

from posthog.schema import StickinessOperator, StickinessQuery

from posthog.hogql_queries.validation.validation import QueryValidationContext

STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE = "stickiness_criteria_zero_incompatible"


class ValidateStickinessCriteria:
    """Reject `value = 0` when paired with an operator where it is meaningless.

    `value = 0` remains permitted on the schema so that insights persisted
    before pydantic started enforcing `ge=1` still deserialize. Operator-level
    semantics are checked at query time.
    """

    code = STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE

    def validate(self, context: QueryValidationContext[StickinessQuery]) -> None:
        criteria = context.query.stickinessFilter.stickinessCriteria if context.query.stickinessFilter else None
        if criteria is None:
            return

        if criteria.value == 0 and criteria.operator in (StickinessOperator.EXACT, StickinessOperator.LTE):
            raise ValidationError(
                "Stickiness criteria with operator exact or lte must use a value greater than 0.",
                code=STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE,
            )
