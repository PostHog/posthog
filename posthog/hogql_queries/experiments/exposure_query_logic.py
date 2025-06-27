"""
Shared exposure logic for experiment query runners.

This module contains common functions for handling experiment exposures,
including multiple variant handling and exposure filtering logic.
"""

from typing import Optional
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.models.team.team import Team
from posthog.schema import MultipleVariantHandling


def get_multiple_variant_handling_from_experiment(experiment: Experiment) -> MultipleVariantHandling:
    """
    Determines how to handle entities exposed to multiple variants based on experiment configuration.
    """
    if experiment.exposure_criteria and experiment.exposure_criteria.get("multiple_variant_handling"):
        return experiment.exposure_criteria.get("multiple_variant_handling")
    else:
        # Default to "exclude" if not specified (maintains backwards compatibility)
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


def get_test_accounts_filter(team: Team, exposure_criteria: Optional[dict] = None) -> list[ast.Expr]:
    """
    Returns test account filters based on experiment configuration.

    Args:
        team: The team object
        exposure_criteria: Experiment exposure criteria configuration
    """
    filter_test_accounts = False

    if exposure_criteria and exposure_criteria.get("filterTestAccounts"):
        filter_test_accounts = True

    if filter_test_accounts and isinstance(team.test_account_filters, list) and len(team.test_account_filters) > 0:
        return [property_to_expr(property, team) for property in team.test_account_filters]
    return []


def get_exposure_event_and_property(feature_flag_key: str, exposure_criteria: Optional[dict] = None) -> tuple[str, str]:
    """
    Determines which event and feature flag variant property to use for exposures.

    Args:
        feature_flag_key: The feature flag key
        exposure_criteria: Experiment exposure criteria configuration

    Returns:
        Tuple of (event_name, feature_flag_variant_property)
    """
    exposure_config = exposure_criteria.get("exposure_config") if exposure_criteria else None

    if exposure_config and exposure_config.get("event") != "$feature_flag_called":
        # For custom exposure events, we extract the event name from the exposure config
        # and get the variant from the $feature/<key> property
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = exposure_config.get("event")
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
    exposure_criteria: Optional[dict] = None,
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
        *get_test_accounts_filter(team, exposure_criteria),
    ]

    # Add custom exposure property filters if present
    exposure_config = exposure_criteria.get("exposure_config") if exposure_criteria else None
    if exposure_config and exposure_config.get("kind") == "ExperimentEventExposureConfig":
        exposure_property_filters: list[ast.Expr] = []

        if exposure_config.get("properties"):
            for property in exposure_config.get("properties"):
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
