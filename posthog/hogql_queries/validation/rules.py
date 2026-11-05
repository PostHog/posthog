from collections.abc import Sequence

from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelsQuery, LifecycleQuery, RetentionEntity, RetentionQuery, StickinessQuery, TrendsQuery

from posthog.hogql.constants import MAX_EXPANDED_INSIGHT_QUERIES

from posthog.hogql_queries.utils.entities import every_warehouse_series_reads_flag_calls, is_data_warehouse_entity
from posthog.hogql_queries.utils.properties import has_any_property_filters
from posthog.hogql_queries.validation.utils import get_query_insight_name
from posthog.hogql_queries.validation.validation import QueryValidationContext
from posthog.types import EntityNode


class RequireAtLeastOneSeries:
    """Insights need at least one series entity."""

    code = "insight_requires_at_least_one_series"

    def validate(self, context: QueryValidationContext[TrendsQuery | StickinessQuery | LifecycleQuery]) -> None:
        if not context.query.series:
            raise ValidationError(
                f"{get_query_insight_name(context.query)} require at least one series.",
                code=self.code,
            )


class DisallowUnsupportedDataWarehouseSettings:
    """Global property filters, test account filters and sampling can't be used together with data warehouse series.

    A query whose warehouse series all read flag calls takes global property filters and test account filters.
    """

    code = "data_warehouse_series_unsupported_settings"

    def validate(
        self,
        context: QueryValidationContext[TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery | RetentionQuery],
    ) -> None:
        series = _series_entities(context.query)
        if not any(is_data_warehouse_entity(node) for node in series):
            return

        unsupported_settings: list[str] = []
        if not every_warehouse_series_reads_flag_calls(series):
            if has_any_property_filters(context.query.properties):
                unsupported_settings.append("filters")
            if context.query.filterTestAccounts:
                unsupported_settings.append("test account filters")
        if context.query.samplingFactor is not None:
            unsupported_settings.append("sampling")

        if unsupported_settings:
            settings = " and ".join(unsupported_settings)
            verb = "is" if unsupported_settings == ["sampling"] else "are"
            raise ValidationError(
                f"{settings.capitalize()} {verb} not supported for {get_query_insight_name(context.query).lower()} with a data warehouse series.",
                code=self.code,
            )


def _series_entities(
    query: TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery | RetentionQuery,
) -> Sequence[EntityNode | RetentionEntity | None]:
    if isinstance(query, RetentionQuery):
        return [query.retentionFilter.targetEntity, query.retentionFilter.returningEntity]
    return query.series


SERIES_FAN_OUT_TOO_LARGE = "insight_series_fan_out_too_large"


def expanded_series_count(query: TrendsQuery | StickinessQuery, *, cohort_breakdown_expands: bool) -> int:
    """How many ClickHouse queries this insight expands into, one per series after breakdown and compare.

    The caller decides whether a cohort breakdown expands, because a conjoined cohort breakdown
    resolves to a single query per series instead of one per cohort.
    """
    count = len(query.series)

    breakdown_filter = getattr(query, "breakdownFilter", None)
    if cohort_breakdown_expands and breakdown_filter is not None and isinstance(breakdown_filter.breakdown, list):
        count *= max(1, len(breakdown_filter.breakdown))

    if query.compareFilter is not None and query.compareFilter.compare:
        count *= 2

    return count


def validate_series_fan_out(query: TrendsQuery | StickinessQuery, *, cohort_breakdown_expands: bool) -> None:
    """Reject an insight that expands into more queries than one request is allowed to run.

    Runners call this from setup_series rather than from validators(), because setup_series copies
    the whole query once per cohort and runs before the standard validation rules do.
    """
    count = expanded_series_count(query, cohort_breakdown_expands=cohort_breakdown_expands)
    if count > MAX_EXPANDED_INSIGHT_QUERIES:
        raise ValidationError(
            f"This insight needs {count} queries to run, which is over the limit of {MAX_EXPANDED_INSIGHT_QUERIES}. "
            f"Use fewer series, break down by fewer cohorts, or turn off comparing to the previous period.",
            code=SERIES_FAN_OUT_TOO_LARGE,
        )
