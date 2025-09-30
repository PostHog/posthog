"""
Shared exposure logic for experiment query runners.

This module contains common functions for handling experiment exposures,
including multiple variant handling and exposure filtering logic.
"""

from typing import Optional, Union

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureCriteria, MultipleVariantHandling

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team


def normalize_to_exposure_criteria(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> Optional[ExperimentExposureCriteria]:
    """
    Normalizes various input types to a properly typed ExperimentExposureCriteria object.

    This handles the conversion from:
    - Django Experiment models (extracts exposure_criteria field)
    - Plain dictionaries (from JSONFields)
    - Already typed ExperimentExposureCriteria objects (passthrough)
    - None values

    Returns:
        ExperimentExposureCriteria object or None
    """
    if exposure_criteria is None:
        return None

    # Already a typed object, return as-is
    if isinstance(exposure_criteria, ExperimentExposureCriteria):
        return exposure_criteria

    # Convert dict to typed object
    if isinstance(exposure_criteria, dict):
        # Create a copy to avoid mutating the input
        criteria_copy = exposure_criteria.copy()
        # Also normalize nested exposure_config if present
        if criteria_copy.get("exposure_config"):
            exposure_config = criteria_copy["exposure_config"]
            if isinstance(exposure_config, dict):
                criteria_copy["exposure_config"] = ExperimentEventExposureConfig.model_validate(exposure_config)

        return ExperimentExposureCriteria.model_validate(criteria_copy)


def get_multiple_variant_handling_from_experiment(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> MultipleVariantHandling:
    """
    Determines how to handle entities exposed to multiple variants based on experiment configuration.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    if criteria and criteria.multiple_variant_handling:
        return criteria.multiple_variant_handling

    # Default to "exclude" if not specified
    return MultipleVariantHandling.EXCLUDE


def get_variant_selection_expr(
    feature_flag_variant_property: str, multiple_variant_handling: MultipleVariantHandling
) -> ast.Expr:
    """
    Returns the appropriate variant selection expression based on multiple_variant_handling configuration.

    Args:
        feature_flag_variant_property: The property name containing the variant value
        multiple_variant_handling: How to handle multiple exposures (EXCLUDE or FIRST_SEEN)
    """
    variant_property_field = ast.Field(chain=["properties", feature_flag_variant_property])

    match multiple_variant_handling:
        case MultipleVariantHandling.FIRST_SEEN:
            # Use variant from earliest exposure (minimum timestamp)
            return parse_expr(
                "argMin({variant_property}, timestamp)",
                placeholders={
                    "variant_property": variant_property_field,
                },
            )
        case _:
            # Default behavior is EXCLUDE. Users who have seen more than one variant is assigned to the
            # MULTIPLE_VARIANT_KEY group
            return parse_expr(
                "if(count(distinct {variant_property}) > 1, {multiple_variant_key}, any({variant_property}))",
                placeholders={
                    "variant_property": variant_property_field,
                    "multiple_variant_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )


def get_test_accounts_filter(
    team: Team, exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None
) -> list[ast.Expr]:
    """
    Returns test account filters based on experiment configuration.

    Args:
        team: The team object
        exposure_criteria: Experiment exposure criteria configuration
    """
    # Normalize to typed object
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    filter_test_accounts = criteria.filterTestAccounts if criteria else False

    if filter_test_accounts and isinstance(team.test_account_filters, list) and len(team.test_account_filters) > 0:
        return [property_to_expr(property, team) for property in team.test_account_filters]
    return []


def get_exposure_event_and_property(
    feature_flag_key: str, exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None
) -> tuple[str, str]:
    """
    Determines which event and feature flag variant property to use for exposures.

    Args:
        feature_flag_key: The feature flag key
        exposure_criteria: Experiment exposure criteria configuration

    Returns:
        Tuple of (event_name, feature_flag_variant_property)
    """
    # Normalize to typed object
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    exposure_config = criteria.exposure_config if criteria else None

    if exposure_config and exposure_config.event and exposure_config.event != "$feature_flag_called":
        # For custom exposure events, we extract the event name from the exposure config
        # and get the variant from the $feature/<key> property
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = exposure_config.event
    else:
        # For the default $feature_flag_called event, we need to get the variant from $feature_flag_response
        feature_flag_variant_property = "$feature_flag_response"
        event = "$feature_flag_called"

    return event, feature_flag_variant_property


def build_common_exposure_conditions(
    event: str,
    feature_flag_variant_property: str,
    variants: list[str],
    date_range_query: QueryDateRange,
    team: Team,
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None,
    feature_flag_key: Optional[str] = None,
) -> list[ast.Expr]:
    """
    Builds common exposure conditions that are shared across exposure queries.

    Args:
        event: The exposure event name
        feature_flag_variant_property: Property containing the variant value
        variants: List of valid variant keys
        date_range_query: Date range for the query
        team: Team object for test account filtering
        exposure_criteria: Experiment exposure criteria configuration
        feature_flag_key: Feature flag key (required for $feature_flag_called events)
    """
    # Normalize to typed object
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    exposure_conditions: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=date_range_query.date_from()),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=date_range_query.date_to()),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=event),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["properties", feature_flag_variant_property]),
            right=ast.Constant(value=variants),
        ),
        *get_test_accounts_filter(team, criteria),
    ]

    # Add custom exposure property filters if present
    exposure_config = criteria.exposure_config if criteria else None

    if exposure_config and exposure_config.kind == "ExperimentEventExposureConfig" and exposure_config.properties:
        exposure_property_filters: list[ast.Expr] = []

        for property in exposure_config.properties:
            exposure_property_filters.append(property_to_expr(property, team))

        if exposure_property_filters:
            exposure_conditions.append(ast.And(exprs=exposure_property_filters))

    # For the $feature_flag_called events, we need an additional filter to ensure the event is for the correct feature flag
    if event == "$feature_flag_called" and feature_flag_key:
        exposure_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", "$feature_flag"]),
                right=ast.Constant(value=feature_flag_key),
            ),
        )

    return exposure_conditions


def get_entity_key(group_type_index: Optional[int]) -> str:
    """
    Returns the appropriate entity key based on whether we're dealing with groups or persons.

    Args:
        group_type_index: Group type index if using groups, None for persons

    Returns:
        Entity key string (either "person_id" or "$group_{index}")
    """
    if isinstance(group_type_index, int):
        return f"$group_{group_type_index}"
    return "person_id"
