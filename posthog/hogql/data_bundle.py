from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union
from uuid import UUID

from posthog.hogql.models import (
    TeamDataClass,
    UserDataClass,
    CohortDataClass,
    ActionDataClass,
    PropertyDefinitionDataClass,
    InsightVariableDataClass,
    ElementDataClass,
    GroupTypeMappingDataClass,
)


@dataclass
class HogQLDataBundle:
    """
    Bundle containing all the data needed for HogQL operations without ORM dependencies.
    This should be constructed from ORM data at the boundary and passed through the context.
    """
    
    team: TeamDataClass
    user: Optional[UserDataClass] = None
    
    # Lookup dictionaries for efficient access
    cohorts_by_id: Dict[int, CohortDataClass] = field(default_factory=dict)
    cohorts_by_name: Dict[str, CohortDataClass] = field(default_factory=dict)
    
    actions_by_id: Dict[int, ActionDataClass] = field(default_factory=dict)
    actions_by_name: Dict[str, ActionDataClass] = field(default_factory=dict)
    
    property_definitions_by_key: Dict[str, List[PropertyDefinitionDataClass]] = field(default_factory=dict)
    
    insight_variables_by_id: Dict[Union[str, UUID], InsightVariableDataClass] = field(default_factory=dict)
    insight_variables_by_code_name: Dict[str, InsightVariableDataClass] = field(default_factory=dict)
    
    # Group type mappings for field traversal
    group_type_mappings: List[GroupTypeMappingDataClass] = field(default_factory=list)
    
    # Data warehouse joins and table info (simplified for now)
    data_warehouse_joins: Dict[str, dict] = field(default_factory=dict)
    data_warehouse_tables: Dict[str, dict] = field(default_factory=dict)

    def get_cohort_by_id(self, cohort_id: int) -> Optional[CohortDataClass]:
        """Get cohort by ID"""
        return self.cohorts_by_id.get(cohort_id)

    def get_cohort_by_name(self, name: str) -> Optional[CohortDataClass]:
        """Get cohort by name"""
        return self.cohorts_by_name.get(name)

    def get_action_by_id(self, action_id: int) -> Optional[ActionDataClass]:
        """Get action by ID"""
        return self.actions_by_id.get(action_id)

    def get_action_by_name(self, name: str) -> Optional[ActionDataClass]:
        """Get action by name"""
        return self.actions_by_name.get(name)

    def get_property_definitions(self, key: str) -> List[PropertyDefinitionDataClass]:
        """Get property definitions by key"""
        return self.property_definitions_by_key.get(key, [])

    def get_insight_variable_by_id(self, var_id: Union[str, UUID]) -> Optional[InsightVariableDataClass]:
        """Get insight variable by ID"""
        return self.insight_variables_by_id.get(var_id)

    def get_insight_variable_by_code_name(self, code_name: str) -> Optional[InsightVariableDataClass]:
        """Get insight variable by code name"""
        return self.insight_variables_by_code_name.get(code_name)

    def get_filtered_property_definitions(
        self,
        key: str,
        property_type: Optional[str] = None,
        group_type_index: Optional[int] = None
    ) -> List[PropertyDefinitionDataClass]:
        """Get filtered property definitions"""
        definitions = self.get_property_definitions(key)
        
        if property_type:
            from posthog.hogql.models import PropertyDefinitionType
            type_map = {
                "person": PropertyDefinitionType.PERSON,
                "event": PropertyDefinitionType.EVENT,
                "group": PropertyDefinitionType.GROUP,
                "session": PropertyDefinitionType.SESSION,
            }
            target_type = type_map.get(property_type)
            if target_type:
                definitions = [pd for pd in definitions if pd.type == target_type]
        
        if group_type_index is not None:
            definitions = [pd for pd in definitions if pd.group_type_index == group_type_index]
        
        # Filter by team/project
        definitions = [
            pd for pd in definitions 
            if pd.effective_project_id == self.team.project_id
        ]
        
        return definitions


def create_data_bundle_from_orm(team_id: int, project_id: Optional[int] = None, user_id: Optional[int] = None) -> HogQLDataBundle:
    """
    Factory function to create HogQLDataBundle from ORM models.
    This should be called at the boundary to convert ORM data to dataclasses.
    """
    from django.db.models.functions.comparison import Coalesce
    from django.db import models
    from posthog.models import (
        Team,
        User,
        Cohort,
        Action,
        PropertyDefinition,
        InsightVariable,
    )
    from posthog.models.group_type_mapping import GroupTypeMapping
    from posthog.warehouse.models import DataWarehouseJoin
    
    # Get team
    team_orm = Team.objects.get(id=team_id)
    team_data = TeamDataClass(
        id=team_orm.id,
        project_id=team_orm.project_id,
        timezone=team_orm.timezone,
        test_account_filters=team_orm.test_account_filters or [],
        path_cleaning_filters=team_orm.path_cleaning_filters or []
    )
    
    # Get user if requested
    user_data = None
    if user_id:
        try:
            user_orm = User.objects.get(id=user_id)
            user_data = UserDataClass(
                id=user_orm.id,
                email=user_orm.email,
                first_name=user_orm.first_name,
                is_active=user_orm.is_active
            )
        except User.DoesNotExist:
            pass
    
    # Get cohorts for this project
    cohorts_by_id = {}
    cohorts_by_name = {}
    cohort_orms = Cohort.objects.filter(team__project_id=team_data.project_id, deleted=False)
    for cohort_orm in cohort_orms:
        cohort_data = CohortDataClass(
            id=cohort_orm.id,
            name=cohort_orm.name,
            team_id=cohort_orm.team_id,
            project_id=team_data.project_id,
            deleted=cohort_orm.deleted,
            filters=cohort_orm.filters,
            is_static=cohort_orm.is_static
        )
        cohorts_by_id[cohort_data.id] = cohort_data
        if cohort_data.name:
            cohorts_by_name[cohort_data.name] = cohort_data
    
    # Get actions for this project
    actions_by_id = {}
    actions_by_name = {}
    action_orms = Action.objects.filter(team__project_id=team_data.project_id, deleted=False)
    for action_orm in action_orms:
        action_data = ActionDataClass(
            id=action_orm.id,
            name=action_orm.name,
            team_id=action_orm.team_id,
            project_id=team_data.project_id,
            steps_json=action_orm.steps_json or []
        )
        actions_by_id[action_data.id] = action_data
        if action_data.name:
            actions_by_name[action_data.name] = action_data
    
    # Get property definitions for this project
    property_definitions_by_key = {}
    property_definition_orms = PropertyDefinition.objects.alias(
        effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
    ).filter(
        effective_project_id=team_data.project_id
    )
    
    for pd_orm in property_definition_orms:
        pd_data = PropertyDefinitionDataClass(
            name=pd_orm.name,
            type=pd_orm.type,
            property_type=pd_orm.property_type,
            team_id=pd_orm.team_id,
            project_id=pd_orm.project_id,
            group_type_index=pd_orm.group_type_index
        )
        
        if pd_data.name not in property_definitions_by_key:
            property_definitions_by_key[pd_data.name] = []
        property_definitions_by_key[pd_data.name].append(pd_data)
    
    # Get insight variables for this team
    insight_variables_by_id = {}
    insight_variables_by_code_name = {}
    insight_variable_orms = InsightVariable.objects.filter(team_id=team_id)
    for iv_orm in insight_variable_orms:
        iv_data = InsightVariableDataClass(
            id=iv_orm.id,
            team_id=iv_orm.team_id,
            name=iv_orm.name,
            type=iv_orm.type,
            code_name=iv_orm.code_name,
            default_value=iv_orm.default_value
        )
        insight_variables_by_id[iv_data.id] = iv_data
        if iv_data.code_name:
            insight_variables_by_code_name[iv_data.code_name] = iv_data
    
    # Get group type mappings for this project
    group_type_mappings = []
    group_mapping_orms = GroupTypeMapping.objects.filter(project_id=team_data.project_id)
    for mapping_orm in group_mapping_orms:
        mapping_data = GroupTypeMappingDataClass(
            group_type=mapping_orm.group_type,
            group_type_index=mapping_orm.group_type_index,
            name_singular=mapping_orm.name_singular,
            name_plural=mapping_orm.name_plural
        )
        group_type_mappings.append(mapping_data)
    
    # Get data warehouse joins (simplified)
    data_warehouse_joins = {}
    dw_joins = DataWarehouseJoin.objects.filter(team_id=team_id).filter(
        models.Q(deleted__isnull=True) | models.Q(deleted=False)
    )
    for join in dw_joins:
        key = f"{join.source_table_name}.{join.field_name}"
        data_warehouse_joins[key] = {
            "joining_table_name": join.joining_table_name,
            "source_table_name": join.source_table_name,
            "field_name": join.field_name,
        }
    
    return HogQLDataBundle(
        team=team_data,
        user=user_data,
        cohorts_by_id=cohorts_by_id,
        cohorts_by_name=cohorts_by_name,
        actions_by_id=actions_by_id,
        actions_by_name=actions_by_name,
        property_definitions_by_key=property_definitions_by_key,
        insight_variables_by_id=insight_variables_by_id,
        insight_variables_by_code_name=insight_variables_by_code_name,
        group_type_mappings=group_type_mappings,
        data_warehouse_joins=data_warehouse_joins,
    )