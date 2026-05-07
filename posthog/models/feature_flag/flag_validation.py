"""
Flag validation utilities for feature flag creation/updates in the admin UI.

These functions validate that feature flags can be evaluated without timing out
by testing the underlying database queries.
"""

from typing import Optional, Union, cast

from django.db.models import BooleanField, CharField, Expression, F, Func
from django.db.models.expressions import ExpressionWrapper, RawSQL
from django.db.models.query import QuerySet

from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.models.cohort import Cohort, CohortOrEmpty
from posthog.models.filters import Filter
from posthog.models.group import Group
from posthog.models.person import Person
from posthog.models.property.property import Property
from posthog.person_db_router import PERSONS_DB_FOR_READ
from posthog.queries.base import properties_to_Q, sanitize_property_key

from .feature_flag import FeatureFlag

READ_ONLY_DATABASE_FOR_PERSONS = PERSONS_DB_FOR_READ


def key_and_field_for_property(property: Property) -> tuple[str, str]:
    """
    Generate database field names for property matching with math operators.

    Returns tuple of (annotation_key, field_path) for use in Django ORM queries.
    """
    column = "group_properties" if property.type == "group" else "properties"
    key = property.key
    sanitized_key = sanitize_property_key(key)

    return (
        f"{column}_{sanitized_key}_type",
        f"{column}__{key}",
    )


def get_all_properties_with_math_operators(
    properties: list[Property], cohorts_cache: dict[int, CohortOrEmpty], project_id: int
) -> list[tuple[str, str]]:
    """
    Recursively extract all properties that use math operators (gt, lt, gte, lte).

    These properties require special JSONB type annotations in the database query
    to ensure proper comparison semantics.
    """
    all_keys_and_fields = []

    for prop in properties:
        if prop.type == "cohort":
            cohort_id = int(cast(Union[str, int], prop.value))
            if cohorts_cache.get(cohort_id) is None:
                queried_cohort = (
                    Cohort.objects.db_manager(DATABASE_FOR_FLAG_MATCHING)
                    .filter(pk=cohort_id, team__project_id=project_id, deleted=False)
                    .first()
                )
                cohorts_cache[cohort_id] = queried_cohort or ""

            cohort = cohorts_cache[cohort_id]
            if cohort:
                all_keys_and_fields.extend(
                    get_all_properties_with_math_operators(cohort.properties.flat, cohorts_cache, project_id)
                )
        elif prop.operator in ["gt", "lt", "gte", "lte"] and prop.type in ("person", "group"):
            all_keys_and_fields.append(key_and_field_for_property(prop))

    return all_keys_and_fields


def _get_property_type_annotations(properties_with_math_operators):
    """
    Generate Django ORM annotations for JSONB property type extraction.

    This allows the database to properly cast and compare JSONB values
    when using math operators like gt/lt.
    """
    return {
        prop_key: Func(F(prop_field), function="JSONB_TYPEOF", output_field=CharField())
        for prop_key, prop_field in properties_with_math_operators
    }


def _exclude_realtime_backfilled_cohort_properties(
    properties: list[Property], project_id: int, *, allow_realtime_backfilled: bool = False
) -> list[Property]:
    """
    When allow_realtime_backfilled is True, filters out cohort properties that reference
    realtime+backfilled cohorts from the property list. These cohorts are evaluated by the
    Rust flag service via cohort_membership table lookups and don't need Django ORM query
    validation.

    When False, returns the property list unchanged.
    """
    if not allow_realtime_backfilled:
        return properties

    result = []
    for prop in properties:
        if prop.type == "cohort":
            try:
                cohort = Cohort.objects.get(
                    pk=int(cast(Union[str, int], prop.value)),
                    team__project_id=project_id,
                    deleted=False,
                )
                if cohort.is_flag_compatible:
                    continue
            except (Cohort.DoesNotExist, ValueError):
                pass
        result.append(prop)
    return result


def _base_query_for_aggregation(group_type_index: Optional[int], team_id: int) -> QuerySet:
    """Return the appropriate Person or Group queryset for a given aggregation type."""
    if group_type_index is None:
        return Person.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(  # nosemgrep: no-direct-persons-db-orm
            team_id=team_id
        )  # nosemgrep: no-direct-persons-db-orm
    return Group.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(  # nosemgrep: no-direct-persons-db-orm
        team_id=team_id, group_type_index=group_type_index
    )


def check_flag_evaluation_query_is_ok(
    feature_flag: FeatureFlag, team_id: int, project_id: int, *, allow_realtime_backfilled: bool = False
) -> None:
    """
    Validate that a feature flag's conditions can be evaluated without errors.

    This is a rough simulation of the actual query that will be run during flag evaluation.
    It catches database-level errors that aren't caught by syntax validation, such as:
    - Regex patterns valid in RE2 but not PostgreSQL
    - Property filters that cause query timeouts
    - Malformed property conditions

    Each condition is validated against the queryset matching its own aggregation type,
    which allows flags with mixed person and group conditions to be validated correctly.

    NOTE: This validation is primarily for the admin UI to prevent users from creating
    flags that will fail at evaluation time. Once all flag evaluation moves to the Rust
    service, this validation may need to be updated or removed.

    Args:
        feature_flag: The FeatureFlag instance to validate
        team_id: The team ID the flag belongs to
        project_id: The project ID the flag belongs to

    Raises:
        Any database errors that occur during query execution
    """
    # Group conditions by aggregation type so each set of conditions is validated
    # against the correct base queryset (Person for None, Group for a group_type_index).
    conditions_by_aggregation: dict[Optional[int], list[tuple[int, dict]]] = {}
    for index, condition in enumerate(feature_flag.conditions):
        aggregation = condition.get("aggregation_group_type_index")
        conditions_by_aggregation.setdefault(aggregation, []).append((index, condition))

    for aggregation, conditions in conditions_by_aggregation.items():
        base_query = _base_query_for_aggregation(aggregation, team_id)
        query_fields = []

        for index, condition in conditions:
            key = f"flag_0_condition_{index}"
            property_list = Filter(data=condition).property_groups.flat
            # When realtime cohort flag targeting is enabled, realtime cohorts that have been
            # backfilled are evaluated by the Rust service via cohort_membership lookups, not
            # Django ORM queries. Skip them here so validation doesn't fail trying to translate
            # behavioral filters into SQL.
            property_list = _exclude_realtime_backfilled_cohort_properties(
                property_list, project_id, allow_realtime_backfilled=allow_realtime_backfilled
            )
            expr = properties_to_Q(
                project_id,
                property_list,
            )
            properties_with_math_operators = get_all_properties_with_math_operators(property_list, {}, project_id)
            type_property_annotations = _get_property_type_annotations(properties_with_math_operators)
            base_query = base_query.annotate(
                **type_property_annotations,
                **{
                    key: ExpressionWrapper(
                        # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (literal "true", no user input)
                        cast(Expression, expr if expr else RawSQL("true", [])),
                        output_field=BooleanField(),
                    ),
                },
            )
            query_fields.append(key)

        values = base_query.values(*query_fields)[:10]
        len(values)  # Force query execution to surface any database errors
