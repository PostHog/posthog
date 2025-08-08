from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Optional, Union
from uuid import UUID
from zoneinfo import ZoneInfo

from posthog.models.property import PropertyGroup


class PropertyDefinitionType(IntEnum):
    EVENT = 1
    PERSON = 2
    GROUP = 3
    SESSION = 4


class PropertyType(StrEnum):
    String = "String"
    Boolean = "Boolean"
    Numeric = "Numeric"
    DateTime = "DateTime"
    Duration = "Duration"


@dataclass
class TeamDataClass:
    id: int
    project_id: int
    timezone: str = "UTC"
    test_account_filters: list[dict] = field(default_factory=list)
    path_cleaning_filters: Optional[list[dict]] = None

    @property
    def timezone_info(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def path_cleaning_filter_models(self) -> list[dict]:
        """Return path cleaning filter configuration"""
        return self.path_cleaning_filters or []


@dataclass
class UserDataClass:
    id: int
    email: str
    first_name: str = ""
    is_active: bool = True


@dataclass
class CohortDataClass:
    id: int
    name: Optional[str]
    team_id: int
    project_id: int
    deleted: bool = False
    filters: Optional[dict] = None
    is_static: bool = False

    @property
    def pk(self) -> int:
        return self.id

    @property
    def properties(self) -> PropertyGroup:
        """Convert cohort filters to PropertyGroup"""
        if not self.filters:
            return PropertyGroup(type="AND", values=[])
        
        # This would need the actual conversion logic from the Cohort model
        # For now, returning a basic structure
        return PropertyGroup(type="AND", values=self.filters.get("properties", []))


@dataclass
class ActionStepJSON:
    tag_name: Optional[str] = None
    text: Optional[str] = None
    text_matching: Optional[str] = None
    href: Optional[str] = None
    href_matching: Optional[str] = None
    selector: Optional[str] = None
    url: Optional[str] = None
    url_matching: Optional[str] = "contains"
    event: Optional[str] = None
    properties: Optional[list[dict]] = None


@dataclass
class ActionDataClass:
    id: int
    name: Optional[str]
    team_id: int
    project_id: int
    steps_json: list[dict] = field(default_factory=list)

    @property
    def pk(self) -> int:
        return self.id

    @property
    def steps(self) -> list[ActionStepJSON]:
        return [ActionStepJSON(**step) for step in self.steps_json or []]

    @property
    def team(self) -> "TeamDataClass":
        """Placeholder for team relationship - would need to be injected"""
        return TeamDataClass(id=self.team_id, project_id=self.project_id)


@dataclass
class PropertyDefinitionDataClass:
    name: str
    type: PropertyDefinitionType
    property_type: Optional[PropertyType] = None
    team_id: Optional[int] = None
    project_id: Optional[int] = None
    group_type_index: Optional[int] = None

    @property
    def effective_project_id(self) -> Optional[int]:
        return self.project_id or self.team_id

    class Type:
        EVENT = PropertyDefinitionType.EVENT
        PERSON = PropertyDefinitionType.PERSON
        GROUP = PropertyDefinitionType.GROUP
        SESSION = PropertyDefinitionType.SESSION


@dataclass
class InsightVariableDataClass:
    id: Union[str, UUID]
    team_id: int
    name: str
    type: str
    code_name: Optional[str] = None
    default_value: Any = None

    @property
    def pk(self) -> Union[str, UUID]:
        return self.id


@dataclass
class ElementDataClass:
    """Element data with useful elements constant"""
    
    USEFUL_ELEMENTS = ["a", "button", "input", "select", "textarea", "label"]
    
    tag_name: Optional[str] = None
    text: Optional[str] = None
    href: Optional[str] = None
    attr_id: Optional[str] = None
    attr_class: Optional[list[str]] = None


# Re-export commonly used UUID types
class UUIDType:
    """Placeholder for UUIDT functionality"""
    
    @staticmethod
    def generate() -> str:
        from uuid import uuid4
        return str(uuid4())