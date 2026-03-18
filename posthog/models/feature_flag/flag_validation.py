"""
Flag validation utilities for feature flag creation/updates in the admin UI.

These functions validate that feature flags can be evaluated without timing out
by testing the underlying database queries.
"""

from typing import Union, cast

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


def check_flag_evaluation_query_is_ok(feature_flag: FeatureFlag, team_id: int, project_id: int) -> bool:
    """
    Validate that a feature flag's conditions can be evaluated without errors.

    This is a rough simulation of the actual query that will be run during flag evaluation.
    It catches database-level errors that aren't caught by syntax validation, such as:
    - Regex patterns valid in RE2 but not PostgreSQL
    - Property filters that cause query timeouts
    - Malformed property conditions

    NOTE: This validation is primarily for the admin UI to prevent users from creating
    flags that will fail at evaluation time. Once all flag evaluation moves to the Rust
    service, this validation may need to be updated or removed.

    Args:
        feature_flag: The FeatureFlag instance to validate
        team_id: The team ID the flag belongs to
        project_id: The project ID the flag belongs to

    Returns:
        True if the query executes successfully, False otherwise

    Raises:
        Any database errors that occur during query execution
    """
    group_type_index = feature_flag.aggregation_group_type_index

    base_query: QuerySet = (
        Person.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(team_id=team_id)
        if group_type_index is None
        else Group.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(
            team_id=team_id, group_type_index=group_type_index
        )
    )
    query_fields = []

    for index, condition in enumerate(feature_flag.conditions):
        key = f"flag_0_condition_{index}"
        property_list = Filter(data=condition).property_groups.flat
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
    return len(values) > 0
