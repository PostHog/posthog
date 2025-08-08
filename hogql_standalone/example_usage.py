"""
Example usage of the standalone HogQL system.
This shows how to use HogQL without any Django dependencies.
"""

from typing import TYPE_CHECKING

from .context import StandaloneHogQLContext
from .django_adapter import create_hogql_data_provider_from_team

if TYPE_CHECKING:
    from posthog.models import Team


def example_django_integration(team: "Team"):
    """
    Example of how to use standalone HogQL with Django.
    This is how the current Django code would be refactored.
    """
    # Step 1: Query Django once to get all needed data
    data_provider = create_hogql_data_provider_from_team(team)
    
    # Step 2: Create standalone context (no Django dependencies)
    context = StandaloneHogQLContext(
        data_provider=data_provider,
        enable_select_queries=True,
        debug=True
    )
    
    # Step 3: Access team data without Django models
    team_id = context.team_id
    timezone = context.data_bundle.team.timezone
    has_groups = context.data_bundle.team.has_group_types
    
    print(f"Team {team_id} in {timezone}, has groups: {has_groups}")
    
    # Step 4: Access other data without Django queries
    property_definitions = context.data_bundle.property_definitions
    cohorts = context.data_bundle.cohorts
    actions = context.data_bundle.actions
    
    print(f"Loaded {len(property_definitions)} properties, {len(cohorts)} cohorts, {len(actions)} actions")
    
    return context


def example_microservice_usage():
    """
    Example of how this could be used in a separate microservice.
    The data bundle could be loaded from JSON, protobuf, or API calls.
    """
    from .data_types import HogQLDataBundle, TeamData, OrganizationData, StaticDataProvider
    
    # Data could come from JSON file, protobuf message, or API call
    team_data = TeamData(
        id=1,
        organization_id="org_123",
        timezone="America/New_York",
        has_group_types=True,
        person_on_events_mode=True,
        project_id=1,
    )
    
    organization_data = OrganizationData(
        id="org_123",
        available_product_features=[],
    )
    
    # Create complete data bundle
    data_bundle = HogQLDataBundle(
        team=team_data,
        organization=organization_data,
        # property_definitions, cohorts, etc. would be loaded too
    )
    
    # Create context for HogQL operations
    context = StandaloneHogQLContext(
        data_provider=StaticDataProvider(data_bundle),
        enable_select_queries=True,
    )
    
    # Now HogQL can run without any database or Django dependencies
    team_timezone = context.data_bundle.team.timezone
    print(f"Microservice processing queries for team in {team_timezone}")
    
    return context


def example_webassembly_usage():
    """
    Example of how this could be used in WebAssembly.
    All data is passed in as serialized structures.
    """
    # In WebAssembly, data would be passed from JavaScript
    # as JSON or binary format (protobuf)
    
    import json
    
    # Simulate data coming from JavaScript
    serialized_data = {
        "team": {
            "id": 1,
            "organization_id": "org_123",
            "timezone": "UTC",
            "week_start_day": "SUNDAY",
            "has_group_types": False,
            "person_on_events_mode": True,
            "project_id": 1,
        },
        "organization": {
            "id": "org_123",
            "available_product_features": [],
        },
        "property_definitions": {},
        "cohorts": {},
        "actions": {},
        "insight_variables": {},
        "group_type_mappings": {},
    }
    
    # Convert to our data structures
    # (In real implementation, this would be more robust)
    from .data_types import HogQLDataBundle, TeamData, OrganizationData, StaticDataProvider, WeekStartDay
    
    team_data = TeamData(
        id=serialized_data["team"]["id"],
        organization_id=serialized_data["team"]["organization_id"],
        timezone=serialized_data["team"]["timezone"],
        week_start_day=WeekStartDay.SUNDAY,  # Convert from string
        has_group_types=serialized_data["team"]["has_group_types"],
        person_on_events_mode=serialized_data["team"]["person_on_events_mode"],
        project_id=serialized_data["team"]["project_id"],
    )
    
    organization_data = OrganizationData(
        id=serialized_data["organization"]["id"],
        available_product_features=serialized_data["organization"]["available_product_features"],
    )
    
    data_bundle = HogQLDataBundle(
        team=team_data,
        organization=organization_data,
    )
    
    # Create WebAssembly-compatible context
    context = StandaloneHogQLContext(
        data_provider=StaticDataProvider(data_bundle),
        enable_select_queries=True,
    )
    
    print("WebAssembly HogQL context ready!")
    return context


if __name__ == "__main__":
    # These examples show the progression:
    # 1. Django integration (current PostHog)
    # 2. Microservice (separate Python service)  
    # 3. WebAssembly (browser/edge execution)
    
    print("=== Microservice Example ===")
    microservice_context = example_microservice_usage()
    
    print("\n=== WebAssembly Example ===")  
    wasm_context = example_webassembly_usage()
    
    print(f"\nBoth contexts are ready for HogQL operations!")
    print(f"Microservice team ID: {microservice_context.team_id}")
    print(f"WebAssembly team ID: {wasm_context.team_id}")