"""
Shared exposure logic for experiment query runners.

This module contains common functions for handling experiment exposures,
including multiple variant handling and exposure filtering logic.
"""

import logging
from typing import Optional, Union

from posthog.schema import (
    ActionsNode,
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.team.team import Team

logger = logging.getLogger(__name__)


def _is_actions_node_dict(config: dict) -> bool:
    """
    Helper to determine if a dict represents an ActionsNode.
    Checks for the 'kind' field first as the primary indicator.
    """
    return config.get("kind") == "ActionsNode"


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
                if _is_actions_node_dict(exposure_config):
                    criteria_copy["exposure_config"] = ActionsNode.model_validate(exposure_config)
                else:
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
) -> tuple[Optional[str], str]:
    """
    Determines which event and feature flag variant property to use for exposures.

    Args:
        feature_flag_key: The feature flag key
        exposure_criteria: Experiment exposure criteria configuration

    Returns:
        Tuple of (event_name, feature_flag_variant_property)
        event_name can be None for ActionsNode (actions can match multiple events)
    """
    # Normalize to typed object
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    exposure_config = criteria.exposure_config if criteria else None

    # Handle ActionsNode
    if isinstance(exposure_config, ActionsNode):
        # For actions, we don't filter by event name (actions can match multiple events)
        # The action filter will be applied in build_common_exposure_conditions
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = None
    elif (
        exposure_config
        and hasattr(exposure_config, "event")
        and exposure_config.event
        and exposure_config.event != "$feature_flag_called"
    ):
        # For custom exposure events, we extract the event name from the exposure config
        # and get the variant from the $feature/<key> property
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = exposure_config.event
    else:
        # For the default $feature_flag_called event, we need to get the variant from $feature_flag_response
        feature_flag_variant_property = "$feature_flag_response"
        event = "$feature_flag_called"

    return event, feature_flag_variant_property


def _get_event_name_from_config(exposure_config: Optional[Union[ActionsNode, ExperimentEventExposureConfig]]) -> str:
    """Extract event name from exposure config, defaulting to $feature_flag_called."""
    if not exposure_config or not hasattr(exposure_config, "event"):
        return "$feature_flag_called"

    event = exposure_config.event
    return event if event and event != "$feature_flag_called" else "$feature_flag_called"


def _build_action_filter(action_id: int, team: Team) -> ast.Expr:
    """Build filter expression for an action, returning False if action not found."""
    try:
        action = Action.objects.get(pk=action_id, team=team)
        return action_to_expr(action)
    except Action.DoesNotExist:
        logger.warning(f"Action {action_id} not found for team {team.id}. Exposure query will return no results.")
        return ast.Constant(value=False)


def _build_event_filters(
    exposure_config: Optional[Union[ActionsNode, ExperimentEventExposureConfig]],
    team: Team,
    feature_flag_key: Optional[str],
) -> list[ast.Expr]:
    """Build event/action filters based on exposure config."""
    # Handle action-based exposure
    if isinstance(exposure_config, ActionsNode):
        return [_build_action_filter(int(exposure_config.id), team)]

    # Handle event-based exposure
    event = _get_event_name_from_config(exposure_config)
    filters: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=event),
        )
    ]

    # Add feature flag key filter for $feature_flag_called events
    if event == "$feature_flag_called" and feature_flag_key:
        filters.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", "$feature_flag"]),
                right=ast.Constant(value=feature_flag_key),
            )
        )

    return filters


def _build_property_filters(
    exposure_config: Optional[Union[ActionsNode, ExperimentEventExposureConfig]], team: Team
) -> list[ast.Expr]:
    """Build property filters from exposure config."""
    if not exposure_config or exposure_config.kind != "ExperimentEventExposureConfig" or not exposure_config.properties:
        return []

    property_filters = [property_to_expr(prop, team) for prop in exposure_config.properties]
    return [ast.And(exprs=property_filters)] if property_filters else []


def build_common_exposure_conditions(
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
        feature_flag_variant_property: Property containing the variant value
        variants: List of valid variant keys
        date_range_query: Date range for the query
        team: Team object for test account filtering
        exposure_criteria: Experiment exposure criteria configuration
        feature_flag_key: Feature flag key (required for $feature_flag_called events)
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    exposure_config = criteria.exposure_config if criteria else None

    return [
        # Date range filters
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
        # Variant filter
        ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["properties", feature_flag_variant_property]),
            right=ast.Constant(value=variants),
        ),
        # Test accounts filter
        *get_test_accounts_filter(team, criteria),
        # Event/action filters
        *_build_event_filters(exposure_config, team, feature_flag_key),
        # Property filters
        *_build_property_filters(exposure_config, team),
    ]


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
