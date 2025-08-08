"""
Dependency injection interfaces for HogQL standalone operation.
These define the data contracts needed to run HogQL without Django models.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional, Dict, List, Union
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


# Core data interfaces that HogQL needs
class TeamData(ABC):
    """Interface for team configuration data needed by HogQL"""
    
    @property
    @abstractmethod
    def id(self) -> int:
        pass
    
    @property
    @abstractmethod
    def organization_id(self) -> Optional[str]:
        pass
    
    @property
    @abstractmethod
    def timezone(self) -> str:
        pass
    
    @property
    @abstractmethod
    def week_start_day(self) -> WeekStartDay:
        pass
    
    @property
    @abstractmethod
    def has_group_types(self) -> bool:
        pass
    
    @property
    @abstractmethod
    def person_on_events_mode(self) -> bool:
        pass


class PropertyDefinitionData(ABC):
    """Interface for property definition metadata"""
    
    @property
    @abstractmethod
    def id(self) -> str:
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def property_type(self) -> PropertyType:
        pass
    
    @property
    @abstractmethod
    def group_type_index(self) -> Optional[int]:
        pass
    
    @property
    @abstractmethod
    def is_numerical(self) -> bool:
        pass


class CohortData(ABC):
    """Interface for cohort definition data"""
    
    @property
    @abstractmethod
    def id(self) -> int:
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def query(self) -> Optional[Dict[str, Any]]:
        pass
    
    @property
    @abstractmethod
    def is_static(self) -> bool:
        pass


class ActionData(ABC):
    """Interface for action definition data"""
    
    @property
    @abstractmethod
    def id(self) -> int:
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def steps(self) -> List[Dict[str, Any]]:
        pass


class InsightVariableData(ABC):
    """Interface for insight variable data"""
    
    @property
    @abstractmethod
    def id(self) -> str:
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def code_name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def default_value(self) -> Any:
        pass
    
    @property
    @abstractmethod
    def value(self) -> Any:
        pass


class GroupTypeMappingData(ABC):
    """Interface for group type mapping data"""
    
    @property
    @abstractmethod
    def group_type_index(self) -> int:
        pass
    
    @property
    @abstractmethod
    def group_type(self) -> str:
        pass
    
    @property
    @abstractmethod
    def name_singular(self) -> Optional[str]:
        pass
    
    @property
    @abstractmethod
    def name_plural(self) -> Optional[str]:
        pass


class OrganizationData(ABC):
    """Interface for organization data"""
    
    @property
    @abstractmethod
    def id(self) -> str:
        pass
    
    @property
    @abstractmethod
    def available_product_features(self) -> List[Dict[str, Any]]:
        pass


# Main data provider interface
class HogQLDataProvider(ABC):
    """Main interface for providing all data needed by HogQL"""
    
    @abstractmethod
    def get_team_data(self) -> TeamData:
        """Get team configuration data"""
        pass
    
    @abstractmethod
    def get_property_definitions(self) -> Dict[str, PropertyDefinitionData]:
        """Get all property definitions keyed by property name"""
        pass
    
    @abstractmethod
    def get_cohorts(self) -> Dict[int, CohortData]:
        """Get all cohorts keyed by cohort ID"""
        pass
    
    @abstractmethod
    def get_actions(self) -> Dict[int, ActionData]:
        """Get all actions keyed by action ID"""
        pass
    
    @abstractmethod
    def get_insight_variables(self) -> Dict[str, InsightVariableData]:
        """Get all insight variables keyed by code_name"""
        pass
    
    @abstractmethod
    def get_group_type_mappings(self) -> Dict[int, GroupTypeMappingData]:
        """Get all group type mappings keyed by group_type_index"""
        pass
    
    @abstractmethod
    def get_organization_data(self) -> OrganizationData:
        """Get organization configuration data"""
        pass