"""
Plain Python data types for HogQL standalone operation.
Using dataclasses for type safety without Pydantic overhead.
"""
from dataclasses import dataclass
from typing import Any, Optional, Dict, List, Protocol
from datetime import datetime
from enum import Enum


class WeekStartDay(Enum):
    SUNDAY = 0
    MONDAY = 1


class PropertyType(Enum):
    EVENT = "event"
    PERSON = "person"
    GROUP = "group"
    SESSION = "session"
    FEATURE_FLAG = "feature_flag"


@dataclass(frozen=True)
class TeamData:
    """Team configuration data needed by HogQL"""
    id: int
    organization_id: Optional[str] = None
    timezone: str = "UTC"
    week_start_day: WeekStartDay = WeekStartDay.SUNDAY
    has_group_types: bool = False
    person_on_events_mode: bool = False
    project_id: Optional[int] = None


@dataclass(frozen=True)
class PropertyDefinitionData:
    """Property definition metadata"""
    id: str
    name: str
    property_type: PropertyType
    group_type_index: Optional[int] = None
    is_numerical: bool = False


@dataclass(frozen=True)
class CohortData:
    """Cohort definition data"""
    id: int
    name: str
    query: Optional[Dict[str, Any]] = None
    is_static: bool = False


@dataclass(frozen=True)
class ActionStepData:
    """Action step data"""
    event: Optional[str] = None
    url: Optional[str] = None
    url_matching: Optional[str] = None
    text: Optional[str] = None
    selector: Optional[str] = None
    properties: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.properties is None:
            object.__setattr__(self, 'properties', [])


@dataclass(frozen=True)
class ActionData:
    """Action definition data"""
    id: int
    name: str
    steps: List[ActionStepData] = None
    
    def __post_init__(self):
        if self.steps is None:
            object.__setattr__(self, 'steps', [])


@dataclass(frozen=True)
class InsightVariableData:
    """Insight variable data"""
    id: str
    name: str
    code_name: str
    default_value: Any = None
    value: Any = None


@dataclass(frozen=True)
class GroupTypeMappingData:
    """Group type mapping data"""
    group_type_index: int
    group_type: str
    name_singular: Optional[str] = None
    name_plural: Optional[str] = None


@dataclass(frozen=True)
class OrganizationData:
    """Organization data"""
    id: str
    available_product_features: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.available_product_features is None:
            object.__setattr__(self, 'available_product_features', [])


@dataclass(frozen=True)
class HogQLDataBundle:
    """Complete bundle of all data needed for HogQL operation"""
    team: TeamData
    property_definitions: Dict[str, PropertyDefinitionData] = None
    cohorts: Dict[int, CohortData] = None
    actions: Dict[int, ActionData] = None
    insight_variables: Dict[str, InsightVariableData] = None
    group_type_mappings: Dict[int, GroupTypeMappingData] = None
    organization: OrganizationData = None
    
    def __post_init__(self):
        if self.property_definitions is None:
            object.__setattr__(self, 'property_definitions', {})
        if self.cohorts is None:
            object.__setattr__(self, 'cohorts', {})
        if self.actions is None:
            object.__setattr__(self, 'actions', {})
        if self.insight_variables is None:
            object.__setattr__(self, 'insight_variables', {})
        if self.group_type_mappings is None:
            object.__setattr__(self, 'group_type_mappings', {})
        if self.organization is None:
            # Create a default organization if none provided
            object.__setattr__(self, 'organization', OrganizationData(id=self.team.organization_id or "default"))


# Protocol for data providers (keeps the interface but simpler)
class HogQLDataProvider(Protocol):
    """Protocol for providing data to HogQL"""
    
    def get_data_bundle(self) -> HogQLDataBundle:
        """Get the complete data bundle"""
        ...


class StaticDataProvider:
    """Simple implementation that holds a pre-built data bundle"""
    
    def __init__(self, data_bundle: HogQLDataBundle):
        self._data = data_bundle
    
    def get_data_bundle(self) -> HogQLDataBundle:
        return self._data