from typing import (
    Any,
    Callable,
    ChainMap,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    cast,
)

from django.conf import settings
from django.utils import timezone
from py_expression_eval import Parser
from sentry_sdk.api import capture_exception

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.breakdown_props import get_breakdown_cohort_name
from ee.clickhouse.queries.trends.breakdown import ClickhouseTrendsBreakdown
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from ee.clickhouse.queries.trends.total_volume import ClickhouseTrendsTotalVolume
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE, TRENDS_DISPLAY_BY_VALUE, TRENDS_LIFECYCLE
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.base import InsightResult, convert_to_comparison, determine_compared_filter, handle_compare
from posthog.queries.trends import Trends
from posthog.utils import relative_date_parse


class ClickhouseTrends(ClickhouseTrendsTotalVolume, ClickhouseLifecycle, Trends):
    def run(self, filter: Filter, team: Team, *args, **kwargs):
        """
        Trends are a collection of different aggregations of event data:

         - Total volume: simply filters the events and returns a specified
           aggregation
         - Lifecycle: provides a breakdown of users that are either 'new',
           'returning', 'resurrecting', or 'dormant'
         - Breakdown: provides a breakdown of events by specified criteron

        There are also some options that can be specified for some/all of these:

         - compare: returns an extra set of results that represents the same
           request but for the previous time period
         - formula: allows you to specify a custom formula to calculate the
           results
         - display: specifies how the results should be displayed. This can be
           one of `ActionsLineGraph`, `ActionsPieChart`, `ActionsTable`, etc.
           that is to say the use case this request is part of.
         - cumulative: specifies whether the results should be cumulative, not
           over all of time, but just over the time period specified.

        """
        filter = self._set_default_dates(filter, team.pk)

        # We want to silently ignore any entities that aren't valid
        valid_entities = self._remove_invalid_entities(entities=filter.entities, team_id=team.id)

        # We add names to entities based on their referenced actions
        entities_with_named_actions = self._add_missing_entity_names(entities=valid_entities, team_id=team.pk)

        # First we get the result for the specified range, including performing
        # any formula, breakdown calculations, accumulation etc.
        results = self._get_results_for_requested_range(
            filter=filter, entities=entities_with_named_actions, team_id=team.pk
        )

        # Then, if a comparison was requested, retrieve the results for the
        # previous range, and append these to the results list.
        if filter.compare:
            compared_filter = determine_compared_filter(filter)
            comparison_results = self._get_results_for_requested_range(
                entities=filter.entities, filter=compared_filter, team_id=team.pk
            )

            # HACK: We need to mark these results a compare=True and some other
            # bits so the frontend knows what to do. Possibly better to refactor
            # this into a dedicated method for comparison results generation.
            results = convert_to_comparison(
                trend_entity=cast(List[Dict[str, Any]], results), filter=filter, label="current"
            )

            comparison_results = convert_to_comparison(
                trend_entity=cast(List[Dict[str, Any]], comparison_results), filter=filter, label="previous"
            )

            # Interleave the results with the comparison results, this is how it
            # was done before this refactor.
            results = [result for pair in zip(results, comparison_results) for result in pair]

        return results

    def _remove_invalid_entities(self, entities: List[Entity], team_id: int) -> List[Entity]:
        """
        Remove any entities that are not valid. This includes:

         1. entities that reference non-existent actions

        """
        valid_action_ids = Action.objects.filter(team_id=team_id).values_list("id", flat=True)
        return [
            entity for entity in entities if entity.type != TREND_FILTER_TYPE_ACTIONS or entity.id in valid_action_ids
        ]

    def _add_missing_entity_names(self, entities: List[Entity], team_id: int):
        #  The filter does not have names for action items in entities list, so
        #  we pull these out of the db.
        actions_name_lookup = {
            str(id): name
            for id, name in Action.objects.filter(
                pk__in=[entity.id for entity in entities if entity.type == TREND_FILTER_TYPE_ACTIONS], team_id=team_id
            ).values_list("id", "name")
        }

        # Pull out action names and add them to the entity, if appropriate
        for entity in entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                entity.name = actions_name_lookup.get(str(entity.id))

        return entities

    def _get_results_for_requested_range(self, filter: Filter, entities: List[Entity], team_id: int):
        #  Fetch results for each entity. We keep track of the results for the
        #  entity by assigning an "entity key" (A, B, ... etc).  This is
        #  important as these are needed to be able to apply the
        #  `Filter.formula` that may be present.
        #
        #  Further, we store with the breakdown_value, although this will be
        #  None if no breakdown is specified.
        results_by_entity_by_breakdown_value = self._get_results_for_entities(
            entities=entities, filter=filter, team_id=team_id
        )

        if filter.formula:
            formula_results = self._calculate_formula(
                breakdown_type=filter.breakdown_type,
                formula=filter.formula,
                results_by_entity_by_breakdown_value=results_by_entity_by_breakdown_value,
            )

            # HACK: remove aggregate_value if we don't request an "is_aggregate"
            # display option. I don't want to put this logic further down as
            # I want to make it obvious that it's a hack and not polute the
            # lower layers. I'm only removing this because I don't want to
            # change functionality with this change, but it's possible that just
            # removing this and updating tests that are expecting this
            # functionality would be fine.
            if filter.display not in TRENDS_DISPLAY_BY_VALUE:
                for result in formula_results:
                    del result["aggregated_value"]

            return formula_results

        #  Flatten the results as we do not care about this after this point.
        return [
            result for by_breakdown in results_by_entity_by_breakdown_value.values() for result in by_breakdown.values()
        ]

    def _get_results_for_entities(self, entities: List[Any], filter: Filter, team_id: int):
        #  NOTE: we need to include the entity_index such that we can keep track
        #        of breakdown values across entities. Breakdown values may not
        #        appear across all entities. We want to end up with a result
        #        that includes a formula value for all breakdown values. Where
        #        we are missing an entity value for a specific breakdown value,
        #        we'll fill it with 0.0. This is just to get parity with the
        #        previous implementation
        #        https://github.com/PostHog/posthog/blob/de75cb9d33e9dd771ec7cde12e961ae958dba95c/ee/clickhouse/queries/trends/formula.py

        # Get all the results by entity by breakdown_value. If it's not a
        # breakdown request, we'll just get a None key
        return {
            #  Here we are indexing by A, B, C, etc. This is to match up with
            #  the `filter.formula` format which uses capitalized alpha chars
            #  for representing variables.
            chr(65 + entity_index): {
                result.get("breakdown_value"): result
                for result in self._run_query(filter=filter, team_id=team_id, entity=entity)
            }
            for entity_index, entity in enumerate(entities)
        }

    def _calculate_formula(
        self,
        breakdown_type: Optional[str],
        formula: str,
        results_by_entity_by_breakdown_value: Dict[str, Dict[Union[str, None], InsightResult]],
    ):
        # Invert `results_by_entity_by_breakdown_value` such that we can iterate
        # through each breakdown value and calculate the formula values from
        # then entity results.

        all_breakdown_values_sorted = sorted(
            {
                breakdown_value
                for entity_results in results_by_entity_by_breakdown_value.values()
                for breakdown_value in entity_results.keys()
            },
            # NOTE: I'm putting "all" at the start as this appears to be the
            #  expectation in the tests although I'm not sure it's deliberate. At
            #  any rate, it seems like a sensible default.
            key=lambda x: "0" if x == "all" else str(x).lower(),
        )

        results_by_breakdown_value_by_entity = {
            breakdown_value: {
                entity_index: results_by_breakdown_value[breakdown_value]
                for entity_index, results_by_breakdown_value in results_by_entity_by_breakdown_value.items()
                if breakdown_value in results_by_breakdown_value
            }
            for breakdown_value in all_breakdown_values_sorted
        }

        return [
            calculate_formula_result(
                breakdown_type=breakdown_type,
                formula=formula,
                breakdown_results=breakdown_results,
                breakdown_value=breakdown_value,
            )
            for breakdown_value, breakdown_results in results_by_breakdown_value_by_entity.items()
        ]

    def _set_default_dates(self, filter: Filter, team_id: int) -> Filter:
        data = {}
        if not filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not filter._date_to:
            data.update({"date_to": timezone.now()})
        if data:
            return Filter(data={**filter._data, **data})
        return filter

    def _get_sql_for_entity(self, filter: Filter, entity: Entity, team_id: int) -> Tuple[str, Dict, Callable]:
        if filter.breakdown:
            sql, params, parse_function = ClickhouseTrendsBreakdown(entity, filter, team_id).get_query()
        elif filter.shown_as == TRENDS_LIFECYCLE:
            sql, params, parse_function = self._format_lifecycle_query(entity, filter, team_id)
        else:
            sql, params, parse_function = self._total_volume_query(entity, filter, team_id)

        return sql, params, parse_function

    def _run_query(self, filter: Filter, entity: Entity, team_id: int) -> List[InsightResult]:
        sql, params, parse_function = self._get_sql_for_entity(filter, entity, team_id)
        try:
            result = sync_execute(sql, params)
        except Exception as e:
            capture_exception(e)
            if settings.TEST or settings.DEBUG:
                raise e
            result = []

        result = parse_function(result)
        serialized_data = self._format_serialized(entity, result)

        if filter.display == TRENDS_CUMULATIVE:
            serialized_data = cast(List[InsightResult], self._handle_cumulative(serialized_data))

        return serialized_data


def calculate_formula_result(
    formula: str,
    # NOTE: I don't think we should have to pass `breakdown_type` down, but the
    # result label does something different in a specific case of formula,
    # differeing from the typical breakdown label generation
    breakdown_type: Optional[str],
    breakdown_value: Union[str, int, None],
    breakdown_results: Dict[str, InsightResult],
) -> InsightResult:
    """
    Calculate the formula result for a given breakdown value.

    This is a helper function for the `_run_query` method.
    """
    # We need to build a formula variables value dict for each element in the
    # EntityDict['data'] array. To do this we:

    #  1. qualify the values with their associated entity_key
    qualified_values = [
        [{entity_key: value} for value in result["data"]] for entity_key, result in breakdown_results.items()
    ]

    # 2. zip everything together
    zipped_values = list(zip(*qualified_values))

    #  3. merge all associated values into a single dict
    formula_data_variables = [ChainMap(*value) for value in zipped_values]

    #  Now we can evaluate the formula with these variables
    formula_data_values = [
        evaluate_formula_without_raising(formula=formula, values=dict(formula_values))
        for formula_values in formula_data_variables
    ]

    # We also need to do the same thing with the aggregated value
    aggregated_value = evaluate_formula_without_raising(
        formula=formula,
        values={
            # NOTE: we default to zero even if we do not have any value
            entity_key: result.get("aggregated_value") or 0.0
            for entity_key, result in breakdown_results.items()
        },
    )

    # HACK: I don't think this should be here as it doesn't seem specific to
    # calculation of formulas. The issue comes from the label behaviour being
    # different from the standard breakdown label behaviour
    if breakdown_type == "cohort" and breakdown_value is not None:
        label = get_breakdown_cohort_name(cohort_id=0 if breakdown_value == "all" else int(breakdown_value))
    else:
        label = str(breakdown_value)

    first_result = list(breakdown_results.values())[0]

    # Now take all of the attrs from the first result (arbitrary, hack) and add
    # in our new formula values
    return cast(
        InsightResult,
        {
            "count": sum(formula_data_values),
            # Just use the first results days and labels, they should all be the
            # same anyway
            "days": first_result["days"],
            "labels": first_result["labels"],
            "data": formula_data_values,
            "aggregated_value": aggregated_value,
            "label": label,
        },
    )


def evaluate_formula_without_raising(formula: str, values: Dict[str, Union[float]]) -> Optional[float]:
    """
    Evaluate a formula without raising an exception.

    This is a helper function for the `_run_query` method.
    """
    #  TODO:
    parser = Parser()
    expression = parser.parse(formula)
    variables = expression.variables()
    values_with_zeros = {key: values.get(key, 0.0) for key in variables}
    try:
        return round(expression.evaluate(values_with_zeros), 0)
    except ZeroDivisionError:
        return 0.0
