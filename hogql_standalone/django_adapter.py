"""
Django adapter for converting Django models to HogQL standalone data structures.
This is the bridge between Django and the standalone HogQL system.
"""
from typing import Dict, TYPE_CHECKING

from .data_types import (
    WeekStartDay,
    PropertyType,
    HogQLDataBundle,
    TeamData,
    PropertyDefinitionData,
    CohortData,
    ActionData,
    ActionStepData,
    InsightVariableData,
    GroupTypeMappingData,
    OrganizationData,
    StaticDataProvider,
)

if TYPE_CHECKING:
    from posthog.models import Team


def convert_django_team_to_data_model(team: "Team") -> TeamData:
    """Convert Django Team model to TeamDataModel"""
    from posthog.models.team.team import WeekStartDay as DjangoWeekStartDay
    
    # Convert Django WeekStartDay to our enum
    week_start_mapping = {
        DjangoWeekStartDay.SUNDAY: WeekStartDay.SUNDAY,
        DjangoWeekStartDay.MONDAY: WeekStartDay.MONDAY,
    }
    
    return TeamData(
        id=team.id,
        organization_id=str(team.organization_id) if team.organization_id else None,
        timezone=team.timezone or "UTC",
        week_start_day=week_start_mapping.get(team.week_start_day, WeekStartDay.SUNDAY),
        has_group_types=bool(team.group_type_mapping.exists()) if hasattr(team, 'group_type_mapping') else False,
        person_on_events_mode=getattr(team, 'person_on_events_mode', False) or False,
        project_id=getattr(team, 'project_id', None),
    )


def convert_django_property_definition_to_data_model(prop_def) -> PropertyDefinitionData:
    """Convert Django PropertyDefinition model to PropertyDefinitionDataModel"""
    from posthog.models.property_definition import PropertyType as DjangoPropertyType
    
    # Convert Django PropertyType to our enum
    property_type_mapping = {
        DjangoPropertyType.EVENT: PropertyType.EVENT,
        DjangoPropertyType.PERSON: PropertyType.PERSON,
        DjangoPropertyType.GROUP: PropertyType.GROUP,
        DjangoPropertyType.SESSION: PropertyType.SESSION,
        DjangoPropertyType.FEATURE_FLAG: PropertyType.FEATURE_FLAG,
    }
    
    return PropertyDefinitionData(
        id=str(prop_def.id),
        name=prop_def.name,
        property_type=property_type_mapping.get(prop_def.property_type, PropertyType.EVENT),
        group_type_index=prop_def.group_type_index,
        is_numerical=getattr(prop_def, 'is_numerical', False) or False,
    )


def convert_django_cohort_to_data_model(cohort) -> CohortData:
    """Convert Django Cohort model to CohortDataModel"""
    return CohortData(
        id=cohort.id,
        name=cohort.name,
        query=cohort.query if hasattr(cohort, 'query') else None,
        is_static=getattr(cohort, 'is_static', False) or False,
    )


def convert_django_action_to_data_model(action) -> ActionData:
    """Convert Django Action model to ActionData"""
    steps = []
    if hasattr(action, 'steps') and hasattr(action.steps, 'all'):
        for step in action.steps.all():
            step_data = ActionStepData(
                event=getattr(step, 'event', None),
                url=getattr(step, 'url', None),
                url_matching=getattr(step, 'url_matching', None),
                text=getattr(step, 'text', None),
                selector=getattr(step, 'selector', None),
                properties=getattr(step, 'properties', []),
            )
            steps.append(step_data)
    
    return ActionData(
        id=action.id,
        name=action.name,
        steps=steps,
    )


def convert_django_insight_variable_to_data_model(variable) -> InsightVariableData:
    """Convert Django InsightVariable model to InsightVariableDataModel"""
    return InsightVariableData(
        id=str(variable.id),
        name=variable.name,
        code_name=variable.code_name,
        default_value=variable.default_value,
        value=getattr(variable, 'value', variable.default_value),
    )


def convert_django_group_type_mapping_to_data_model(mapping) -> GroupTypeMappingData:
    """Convert Django GroupTypeMapping model to GroupTypeMappingDataModel"""
    return GroupTypeMappingData(
        group_type_index=mapping.group_type_index,
        group_type=mapping.group_type,
        name_singular=getattr(mapping, 'name_singular', None),
        name_plural=getattr(mapping, 'name_plural', None),
    )


def convert_django_organization_to_data_model(organization) -> OrganizationData:
    """Convert Django Organization model to OrganizationDataModel"""
    available_features = []
    if hasattr(organization, 'available_product_features'):
        if callable(organization.available_product_features):
            available_features = list(organization.available_product_features())
        else:
            available_features = list(organization.available_product_features)
    
    # Convert features to serializable format
    features_data = []
    for feature in available_features:
        if hasattr(feature, '__dict__'):
            features_data.append(vars(feature))
        else:
            features_data.append(str(feature))
    
    return OrganizationData(
        id=str(organization.id),
        available_product_features=features_data,
    )


def create_hogql_data_bundle_from_team(team: "Team") -> HogQLDataBundle:
    """
    Create a complete HogQL data bundle by querying Django for a given team.
    This is the main entry point for converting Django state to HogQL data.
    """
    # Convert team
    team_data = convert_django_team_to_data_model(team)
    
    # Get organization
    organization_data = convert_django_organization_to_data_model(team.organization)
    
    # Get property definitions
    property_definitions = {}
    try:
        from posthog.models.property_definition import PropertyDefinition
        for prop_def in PropertyDefinition.objects.filter(team=team):
            prop_data = convert_django_property_definition_to_data_model(prop_def)
            property_definitions[prop_data.name] = prop_data
    except Exception:
        # If PropertyDefinition import fails or query fails, continue with empty dict
        pass
    
    # Get cohorts
    cohorts = {}
    try:
        from posthog.models import Cohort
        for cohort in Cohort.objects.filter(team=team):
            cohort_data = convert_django_cohort_to_data_model(cohort)
            cohorts[cohort_data.id] = cohort_data
    except Exception:
        # If Cohort import fails or query fails, continue with empty dict
        pass
    
    # Get actions
    actions = {}
    try:
        from posthog.models import Action
        for action in Action.objects.filter(team=team).prefetch_related('steps'):
            action_data = convert_django_action_to_data_model(action)
            actions[action_data.id] = action_data
    except Exception:
        # If Action import fails or query fails, continue with empty dict
        pass
    
    # Get insight variables
    insight_variables = {}
    try:
        from posthog.models.insight_variable import InsightVariable
        for variable in InsightVariable.objects.filter(team=team):
            var_data = convert_django_insight_variable_to_data_model(variable)
            insight_variables[var_data.code_name] = var_data
    except Exception:
        # If InsightVariable import fails or query fails, continue with empty dict
        pass
    
    # Get group type mappings
    group_type_mappings = {}
    try:
        from posthog.models.group_type_mapping import GroupTypeMapping
        for mapping in GroupTypeMapping.objects.filter(team=team):
            mapping_data = convert_django_group_type_mapping_to_data_model(mapping)
            group_type_mappings[mapping_data.group_type_index] = mapping_data
    except Exception:
        # If GroupTypeMapping import fails or query fails, continue with empty dict
        pass
    
    return HogQLDataBundle(
        team=team_data,
        property_definitions=property_definitions,
        cohorts=cohorts,
        actions=actions,
        insight_variables=insight_variables,
        group_type_mappings=group_type_mappings,
        organization=organization_data,
    )


def create_hogql_data_provider_from_team(team: "Team") -> StaticDataProvider:
    """
    Create a HogQLDataProvider from a Django team.
    This is the main entry point for creating a standalone HogQL data provider.
    """
    data_bundle = create_hogql_data_bundle_from_team(team)
    return StaticDataProvider(data_bundle)