"""
Django adapter for converting Django models to readonly dataclasses.
This is the bridge between Django and the standalone HogQL system.
"""
from typing import Dict, List, TYPE_CHECKING

from .readonly_models import (
    ReadonlyDataBundle,
    ReadonlyTeam,
    ReadonlyPropertyDefinition,
    ReadonlyCohort,
    ReadonlyAction,
    ReadonlyActionStep,
    ReadonlyInsightVariable,
    ReadonlyGroupTypeMapping,
    ReadonlyOrganization,
)

if TYPE_CHECKING:
    from posthog.models import Team


def convert_django_team_to_readonly(team: "Team") -> ReadonlyTeam:
    """Convert Django Team model to ReadonlyTeam"""
    return ReadonlyTeam(
        id=team.id,
        project_id=getattr(team, 'project_id', None),
        timezone=team.timezone or "UTC",
        week_start_day=getattr(team, 'week_start_day', 0),
        has_group_types=bool(team.group_type_mapping.exists()) if hasattr(team, 'group_type_mapping') else False,
        person_on_events_mode=getattr(team, 'person_on_events_mode', False) or False,
        path_cleaning_filters=team.path_cleaning_filters if hasattr(team, 'path_cleaning_filters') else None,
    )


def convert_django_property_definition_to_readonly(prop_def) -> ReadonlyPropertyDefinition:
    """Convert Django PropertyDefinition model to ReadonlyPropertyDefinition"""
    from posthog.models.property_definition import PropertyType
    
    # Map Django PropertyType to string
    property_type_str = "String"  # default
    if hasattr(prop_def, 'property_type'):
        if prop_def.property_type == PropertyType.Numeric:
            property_type_str = "Numeric"
        elif prop_def.property_type == PropertyType.Boolean:
            property_type_str = "Boolean"
        elif prop_def.property_type == PropertyType.DateTime:
            property_type_str = "DateTime"
    
    return ReadonlyPropertyDefinition(
        id=str(prop_def.id),
        name=prop_def.name,
        property_type=property_type_str,
        is_numerical=getattr(prop_def, 'is_numerical', False),
        group_type_index=getattr(prop_def, 'group_type_index', None),
    )


def convert_django_cohort_to_readonly(cohort) -> ReadonlyCohort:
    """Convert Django Cohort model to ReadonlyCohort"""
    return ReadonlyCohort(
        id=cohort.id,
        pk=cohort.pk,
        name=cohort.name,
        query=cohort.query if hasattr(cohort, 'query') else None,
        is_static=getattr(cohort, 'is_static', False),
        version=getattr(cohort, 'version', None),
    )


def convert_django_action_to_readonly(action) -> ReadonlyAction:
    """Convert Django Action model to ReadonlyAction"""
    steps = []
    if hasattr(action, 'steps') and hasattr(action.steps, 'all'):
        for step in action.steps.all():
            step_data = ReadonlyActionStep(
                event=getattr(step, 'event', None),
                url=getattr(step, 'url', None),
                url_matching=getattr(step, 'url_matching', None),
                text=getattr(step, 'text', None),
                text_matching=getattr(step, 'text_matching', None),
                href=getattr(step, 'href', None),
                href_matching=getattr(step, 'href_matching', None),
                selector=getattr(step, 'selector', None),
                tag_name=getattr(step, 'tag_name', None),
                properties=getattr(step, 'properties', []),
            )
            steps.append(step_data)
    
    return ReadonlyAction(
        id=action.id,
        name=action.name,
        team=convert_django_team_to_readonly(action.team),
        steps=steps,
    )


def convert_django_insight_variable_to_readonly(variable) -> ReadonlyInsightVariable:
    """Convert Django InsightVariable model to ReadonlyInsightVariable"""
    return ReadonlyInsightVariable(
        id=str(variable.id),
        name=variable.name,
        code_name=variable.code_name,
        default_value=variable.default_value,
        type=getattr(variable, 'type', 'string'),
    )


def convert_django_group_type_mapping_to_readonly(mapping) -> ReadonlyGroupTypeMapping:
    """Convert Django GroupTypeMapping model to ReadonlyGroupTypeMapping"""
    return ReadonlyGroupTypeMapping(
        group_type_index=mapping.group_type_index,
        group_type=mapping.group_type,
        name_singular=getattr(mapping, 'name_singular', None),
        name_plural=getattr(mapping, 'name_plural', None),
    )


def convert_django_organization_to_readonly(organization) -> ReadonlyOrganization:
    """Convert Django Organization model to ReadonlyOrganization"""
    available_features = []
    if hasattr(organization, 'available_product_features'):
        try:
            for feature in organization.available_product_features:
                if hasattr(feature, 'key'):
                    available_features.append(feature.key)
                else:
                    available_features.append(str(feature))
        except (AttributeError, TypeError):
            # Handle case where available_product_features is not iterable
            pass
    
    return ReadonlyOrganization(
        id=str(organization.id),
        available_product_features=available_features,
    )


def create_hogql_data_bundle_from_team(team: "Team") -> ReadonlyDataBundle:
    """
    Create a ReadonlyDataBundle from a Django team.
    This queries all the Django models and converts them to readonly dataclasses.
    """
    # Convert team
    readonly_team = convert_django_team_to_readonly(team)
    
    # Get property definitions
    property_definitions = {}
    try:
        from posthog.models import PropertyDefinition
        from django.db.models.functions.comparison import Coalesce
        from django.db import models
        
        prop_defs = PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(effective_project_id=team.project_id)
        
        for prop_def in prop_defs:
            key = f"{prop_def.name}_{getattr(prop_def, 'type', 'event')}"
            property_definitions[key] = convert_django_property_definition_to_readonly(prop_def)
    except Exception:
        # If we can't load property definitions, continue with empty dict
        pass
    
    # Get cohorts
    cohorts = {}
    try:
        from posthog.models import Cohort
        for cohort in Cohort.objects.filter(team__project_id=team.project_id):
            cohorts[cohort.id] = convert_django_cohort_to_readonly(cohort)
    except Exception:
        pass
    
    # Get actions
    actions = {}
    try:
        from posthog.models import Action
        for action in Action.objects.filter(team=team).prefetch_related('steps'):
            actions[action.id] = convert_django_action_to_readonly(action)
    except Exception:
        pass
    
    # Get insight variables  
    insight_variables = {}
    try:
        from posthog.models import InsightVariable
        for variable in InsightVariable.objects.filter(team=team):
            insight_variables[variable.code_name] = convert_django_insight_variable_to_readonly(variable)
    except Exception:
        pass
    
    # Get group type mappings
    group_type_mappings = {}
    try:
        for mapping in team.group_type_mapping.all():
            group_type_mappings[mapping.group_type_index] = convert_django_group_type_mapping_to_readonly(mapping)
    except Exception:
        pass
    
    # Get organization
    organization = None
    try:
        if hasattr(team, 'organization') and team.organization:
            organization = convert_django_organization_to_readonly(team.organization)
    except Exception:
        pass
    
    return ReadonlyDataBundle(
        team=readonly_team,
        property_definitions=property_definitions,
        cohorts=cohorts,
        actions=actions,
        insight_variables=insight_variables,
        group_type_mappings=group_type_mappings,
        organization=organization,
    )