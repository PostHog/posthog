"""
Pydantic implementations of HogQL data interfaces.
These are the concrete, serializable data structures.
"""
from typing import Any, Optional, Dict, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from .interfaces import (
    TeamData,
    PropertyDefinitionData,
    CohortData,
    ActionData,
    InsightVariableData,
    GroupTypeMappingData,
    OrganizationData,
    HogQLDataProvider,
    WeekStartDay,
    PropertyType,
)


class TeamDataModel(BaseModel, TeamData):
    """Pydantic implementation of TeamData interface"""
    
    model_config = ConfigDict(frozen=True)
    
    id: int
    organization_id: Optional[str] = None
    timezone: str = "UTC"
    week_start_day: WeekStartDay = WeekStartDay.SUNDAY
    has_group_types: bool = False
    person_on_events_mode: bool = False


class PropertyDefinitionDataModel(BaseModel, PropertyDefinitionData):
    """Pydantic implementation of PropertyDefinitionData interface"""
    
    model_config = ConfigDict(frozen=True)
    
    id: str
    name: str
    property_type: PropertyType
    group_type_index: Optional[int] = None
    is_numerical: bool = False


class CohortDataModel(BaseModel, CohortData):
    """Pydantic implementation of CohortData interface"""
    
    model_config = ConfigDict(frozen=True)
    
    id: int
    name: str
    query: Optional[Dict[str, Any]] = None
    is_static: bool = False


class ActionDataModel(BaseModel, ActionData):
    """Pydantic implementation of ActionData interface"""
    
    model_config = ConfigDict(frozen=True)
    
    id: int
    name: str
    steps: List[Dict[str, Any]] = []


class InsightVariableDataModel(BaseModel, InsightVariableData):
    """Pydantic implementation of InsightVariableData interface"""
    
    model_config = ConfigDict(frozen=True)
    
    id: str
    name: str
    code_name: str
    default_value: Any = None
    value: Any = None


class GroupTypeMappingDataModel(BaseModel, GroupTypeMappingData):
    """Pydantic implementation of GroupTypeMappingData interface"""
    
    model_config = ConfigDict(frozen=True)
    
    group_type_index: int
    group_type: str
    name_singular: Optional[str] = None
    name_plural: Optional[str] = None


class OrganizationDataModel(BaseModel, OrganizationData):
    """Pydantic implementation of OrganizationData interface"""
    
    model_config = ConfigDict(frozen=True)
    
    id: str
    available_product_features: List[Dict[str, Any]] = []


class HogQLDataBundle(BaseModel):
    """Complete bundle of all data needed for HogQL operation"""
    
    model_config = ConfigDict(frozen=True)
    
    team: TeamDataModel
    property_definitions: Dict[str, PropertyDefinitionDataModel] = {}
    cohorts: Dict[int, CohortDataModel] = {}
    actions: Dict[int, ActionDataModel] = {}
    insight_variables: Dict[str, InsightVariableDataModel] = {}
    group_type_mappings: Dict[int, GroupTypeMappingDataModel] = {}
    organization: OrganizationDataModel


class HogQLDataBundleProvider(HogQLDataProvider):
    """Implementation of HogQLDataProvider that uses a pre-built data bundle"""
    
    def __init__(self, data_bundle: HogQLDataBundle):
        self._data = data_bundle
    
    def get_team_data(self) -> TeamData:
        return self._data.team
    
    def get_property_definitions(self) -> Dict[str, PropertyDefinitionData]:
        return self._data.property_definitions
    
    def get_cohorts(self) -> Dict[int, CohortData]:
        return self._data.cohorts
    
    def get_actions(self) -> Dict[int, ActionData]:
        return self._data.actions
    
    def get_insight_variables(self) -> Dict[str, InsightVariableData]:
        return self._data.insight_variables
    
    def get_group_type_mappings(self) -> Dict[int, GroupTypeMappingData]:
        return self._data.group_type_mappings
    
    def get_organization_data(self) -> OrganizationData:
        return self._data.organization