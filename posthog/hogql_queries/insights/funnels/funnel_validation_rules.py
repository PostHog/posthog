from itertools import pairwise

from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelsQuery, FunnelVizType, StepOrderValue

from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.hogql_queries.validation.validation import QueryValidationContext


class RequireAtLeastTwoFunnelSteps:
    """Funnels need at least two series entities."""

    def validate(self, context: QueryValidationContext[FunnelsQuery]) -> None:
        if len(context.query.series) < 2:
            raise ValidationError("Funnels require at least two steps.")


class ValidateFunnelStepRange:
    """Make sure the conversion step range is within the bounds of the declared series."""

    def validate(self, context: QueryValidationContext[FunnelsQuery]) -> None:
        max_series_index = len(context.query.series) - 1
        funnels_filter = context.query.funnelsFilter

        if funnels_filter is None:
            return

        if funnels_filter.funnelFromStep is not None:
            if not (0 <= funnels_filter.funnelFromStep <= max_series_index - 1):
                raise ValidationError(
                    f"funnelFromStep is out of bounds. It must be between 0 and {max_series_index - 1}."
                )

        if funnels_filter.funnelToStep is not None:
            if not (1 <= funnels_filter.funnelToStep <= max_series_index):
                raise ValidationError(f"funnelToStep is out of bounds. It must be between 1 and {max_series_index}.")

            if (
                funnels_filter.funnelFromStep is not None
                and funnels_filter.funnelFromStep >= funnels_filter.funnelToStep
            ):
                raise ValidationError(
                    "Funnel step range is invalid. funnelToStep should be greater than funnelFromStep."
                )


class ValidateFunnelExclusions:
    """Prevent exclusion steps from using invalid ranges or overlapping funnel steps."""

    def validate(self, context: QueryValidationContext[FunnelsQuery]) -> None:
        exclusions = context.query.funnelsFilter.exclusions if context.query.funnelsFilter is not None else None
        if exclusions is None:
            return

        series = context.query.series
        for exclusion in exclusions:
            if exclusion.funnelFromStep >= exclusion.funnelToStep:
                raise ValidationError("Exclusion event range is invalid. End of range should be greater than start.")

            if exclusion.funnelFromStep >= len(series) - 1:
                raise ValidationError(
                    "Exclusion event range is invalid. Start of range is greater than number of steps."
                )

            if exclusion.funnelToStep > len(series) - 1:
                raise ValidationError("Exclusion event range is invalid. End of range is greater than number of steps.")

            for entity in series[exclusion.funnelFromStep : exclusion.funnelToStep + 1]:
                if is_equal(entity, exclusion) or is_superset(entity, exclusion):
                    raise ValidationError("Exclusion steps cannot contain an event that's part of funnel steps.")


class ValidateOptionalFunnelSteps:
    """Allow optional steps only for supported funnel types and non-ambiguous step sequences."""

    def validate(self, context: QueryValidationContext[FunnelsQuery]) -> None:
        series = context.query.series
        if not any(getattr(node, "optionalInFunnel", False) for node in series):
            return

        # validate that optional steps are only allowed in Ordered Steps funnels
        funnels_filter = context.query.funnelsFilter
        funnel_viz_type = funnels_filter.funnelVizType if funnels_filter is not None else None
        funnel_order_type = funnels_filter.funnelOrderType if funnels_filter is not None else None

        allows_optional_steps = (
            funnel_viz_type in (FunnelVizType.STEPS, FunnelVizType.FLOW, None)
            and funnel_order_type != StepOrderValue.UNORDERED
        )
        if not allows_optional_steps:
            raise ValidationError(
                'Optional funnel steps are only supported in funnels with step order Sequential or Strict and the graph type "Conversion Steps".'
            )

        # validate that the first step is not optional
        if getattr(series[0], "optionalInFunnel", False):
            raise ValidationError("The first step of a funnel cannot be optional.")

        # Validate that an optional step is not immediately followed by an equivalent required step.
        # In that case, the required step can consume the shared event and the optional step will never convert.
        # Not trying to be overly clever here - putting filters in different order or using SQL queries that are
        # slightly different could get around this, but we want to stop the naive case from spawning support issues.
        for previous_step, current_step in pairwise(series):
            if (
                (is_equal(previous_step, current_step) or is_superset(current_step, previous_step))
                and getattr(previous_step, "optionalInFunnel", False)
                and not getattr(current_step, "optionalInFunnel", False)
            ):
                raise ValidationError("An optional step cannot be the same as the following required step.")
