"""
Query runner for ExperimentsNode - converts experiment selections to exposure event queries.

This runner enables experiments to be used as data sources in insights. It:
1. Takes an ExperimentsNode from the frontend
2. Fetches the experiment configuration from the database
3. Determines the exposure event and properties using existing experiment infrastructure
4. Converts to an EventsNode that queries the exposure events
5. Delegates execution to the standard EventsQueryRunner
"""

from typing import TYPE_CHECKING, Any, Optional

from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, NodeKind, PropertyGroupFilter, PropertyGroupFilterValue

from posthog.hogql_queries.experiments.exposure_query_logic import get_exposure_event_and_property
from posthog.hogql_queries.insights.query_runner import QueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.experiment import Experiment

if TYPE_CHECKING:
    from posthog.schema import ExperimentsNode


def convert_experiments_node_to_events_node(
    experiments_node: "ExperimentsNode | dict[str, Any]", team_id: int
) -> EventsNode:
    """
    Converts an ExperimentsNode to an EventsNode by:
    1. Loading the experiment configuration
    2. Determining the exposure event
    3. Creating property filters for the experiment's feature flag
    4. Merging with any user-specified property filters (e.g., for variant selection)

    Args:
        experiments_node: The ExperimentsNode from the frontend
        team_id: The team ID for loading the experiment

    Returns:
        EventsNode configured to query the experiment's exposure events

    Raises:
        ValidationError: If experiment_id is invalid or experiment not found
    """
    # Handle both dict and typed object formats
    if isinstance(experiments_node, dict):
        experiment_id = experiments_node.get("experiment_id")
        experiment_name = experiments_node.get("experiment_name")
        node_name = experiments_node.get("name")
        custom_name = experiments_node.get("custom_name")
        math = experiments_node.get("math")
        math_property = experiments_node.get("math_property")
        math_property_type = experiments_node.get("math_property_type")
        math_hogql = experiments_node.get("math_hogql")
        math_group_type_index = experiments_node.get("math_group_type_index")
        fixed_properties = experiments_node.get("fixedProperties")
        response = experiments_node.get("response")
        properties = experiments_node.get("properties")
    else:
        experiment_id = experiments_node.experiment_id
        experiment_name = experiments_node.experiment_name
        node_name = experiments_node.name
        custom_name = experiments_node.custom_name
        math = experiments_node.math
        math_property = experiments_node.math_property
        math_property_type = experiments_node.math_property_type
        math_hogql = experiments_node.math_hogql
        math_group_type_index = experiments_node.math_group_type_index
        fixed_properties = experiments_node.fixedProperties
        response = experiments_node.response
        properties = experiments_node.properties

    # Validate experiment_id
    if not experiment_id:
        raise ValidationError("experiment_id is required for ExperimentsNode")

    # Load experiment from database
    try:
        experiment = Experiment.objects.get(
            id=experiment_id,
            team_id=team_id,
        )
    except Experiment.DoesNotExist:
        raise ValidationError(f"Experiment with id {experiment_id} not found")

    # Get exposure event and property using existing experiment infrastructure
    # This handles both default ($feature_flag_called) and custom exposure events
    exposure_event, feature_flag_variant_property = get_exposure_event_and_property(
        experiment.feature_flag.key,
        experiment.exposure_criteria,
    )

    # Build property filters to identify this experiment's exposures
    # We filter for events where the feature flag property matches this experiment's flag
    experiment_properties: list[PropertyGroupFilterValue] = [
        {
            "type": "event",
            "key": "$feature_flag",
            "operator": "exact",
            "value": [experiment.feature_flag.key],
        }
    ]

    # Merge with any user-specified property filters (e.g., for variant selection)
    # This allows users to filter to specific variants like "control" or "test"
    user_properties: Optional[PropertyGroupFilter] = properties
    if user_properties:
        if isinstance(user_properties, dict):
            # Handle PropertyGroupFilter format with "type" and "values"
            if user_properties.get("type") == "AND" and "values" in user_properties:
                experiment_properties.extend(user_properties["values"])
            elif user_properties.get("type") == "OR":
                # Wrap OR filters in an AND group
                experiment_properties.append(user_properties)
        elif isinstance(user_properties, list):
            # Handle list of property filters
            experiment_properties.extend(user_properties)

    # Create the combined property filter
    combined_properties: PropertyGroupFilter = {
        "type": "AND",
        "values": experiment_properties,
    }

    # Create EventsNode with exposure event and properties
    events_node = EventsNode(
        kind=NodeKind.EventsNode,
        event=exposure_event or "$feature_flag_called",
        properties=combined_properties,
        # Copy over common fields from ExperimentsNode
        name=node_name or experiment_name,
        custom_name=custom_name,
        math=math,
        math_property=math_property,
        math_property_type=math_property_type,
        math_hogql=math_hogql,
        math_group_type_index=math_group_type_index,
        fixedProperties=fixed_properties,
        response=response,
    )

    return events_node


class ExperimentsNodeQueryRunner(QueryRunner):
    """
    Query runner for ExperimentsNode.

    This is a thin wrapper that:
    1. Converts ExperimentsNode to EventsNode using experiment exposure configuration
    2. Delegates to EventsQueryRunner for actual query execution

    This allows experiments to be used as data sources in insights while
    leveraging all existing event query infrastructure.
    """

    query: Any  # ExperimentsNode or dict

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Convert ExperimentsNode to EventsNode
        self.events_node = convert_experiments_node_to_events_node(
            self.query,
            self.team.pk,
        )

    def calculate(self):
        """
        Execute the query by delegating to EventsQueryRunner.

        Since we've converted the ExperimentsNode to an EventsNode,
        we can use the standard EventsQueryRunner infrastructure.
        """
        from posthog.hogql_queries.insights.events_query_runner import EventsQueryRunner

        # Create and execute EventsQueryRunner with our converted node
        events_runner = EventsQueryRunner(
            query=self.events_node,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        )

        return events_runner.calculate()

    def to_query(self):
        """
        Convert to HogQL query by delegating to EventsQueryRunner.

        This is used for query inspection and debugging.
        """
        from posthog.hogql_queries.insights.events_query_runner import EventsQueryRunner

        events_runner = EventsQueryRunner(
            query=self.events_node,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
        )

        return events_runner.to_query()
