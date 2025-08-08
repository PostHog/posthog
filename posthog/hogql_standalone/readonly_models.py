"""
Readonly dataclasses that represent the Django models needed by HogQL.
These contain only the data needed for HogQL processing, no Django ORM methods.
"""
from dataclasses import dataclass
from typing import Optional, Any, Dict, List
from datetime import datetime


@dataclass(frozen=True)
class ReadonlyTeam:
    """Readonly version of Django Team model with only the fields HogQL needs"""
    id: int
    project_id: Optional[int] = None
    timezone: str = "UTC"
    week_start_day: int = 0  # 0=Sunday, 1=Monday
    has_group_types: bool = False
    person_on_events_mode: bool = False
    path_cleaning_filters: Optional[List[Dict]] = None

    def path_cleaning_filter_models(self):
        """Mock for path cleaning filters - would need proper implementation"""
        if not self.path_cleaning_filters:
            return []
        # Return simplified path cleaning objects
        return [type('obj', (), {'regex': f.get('regex', ''), 'alias': f.get('alias', '')})() 
                for f in self.path_cleaning_filters]


@dataclass(frozen=True)
class ReadonlyPropertyDefinition:
    """Readonly version of Django PropertyDefinition model"""
    id: str
    name: str
    property_type: str  # "String", "Numeric", "Boolean", etc.
    is_numerical: bool = False
    group_type_index: Optional[int] = None


@dataclass(frozen=True) 
class ReadonlyCohort:
    """Readonly version of Django Cohort model"""
    id: int
    pk: int
    name: str
    query: Optional[Dict] = None
    is_static: bool = False
    version: Optional[int] = None


@dataclass(frozen=True)
class ReadonlyActionStep:
    """Readonly version of Django ActionStep model"""
    event: Optional[str] = None
    url: Optional[str] = None
    url_matching: Optional[str] = None
    text: Optional[str] = None
    text_matching: Optional[str] = None
    href: Optional[str] = None
    href_matching: Optional[str] = None
    selector: Optional[str] = None
    tag_name: Optional[str] = None
    properties: List[Any] = None

    def __post_init__(self):
        if self.properties is None:
            object.__setattr__(self, 'properties', [])


@dataclass(frozen=True)
class ReadonlyAction:
    """Readonly version of Django Action model"""
    id: int
    name: str
    team: ReadonlyTeam
    steps: List[ReadonlyActionStep]


@dataclass(frozen=True)
class ReadonlyInsightVariable:
    """Readonly version of Django InsightVariable model"""
    id: str
    name: str
    code_name: str
    default_value: Any
    type: str


@dataclass(frozen=True)
class ReadonlyGroupTypeMapping:
    """Readonly version of Django GroupTypeMapping model"""
    group_type_index: int
    group_type: str
    name_singular: Optional[str] = None
    name_plural: Optional[str] = None


@dataclass(frozen=True)
class ReadonlyOrganization:
    """Readonly version of Django Organization model"""
    id: str
    available_product_features: List[str]


@dataclass(frozen=True)
class ReadonlyDataBundle:
    """Bundle of all readonly data needed by HogQL"""
    team: ReadonlyTeam
    property_definitions: Dict[str, ReadonlyPropertyDefinition]
    cohorts: Dict[int, ReadonlyCohort] 
    actions: Dict[int, ReadonlyAction]
    insight_variables: Dict[str, ReadonlyInsightVariable]
    group_type_mappings: Dict[int, ReadonlyGroupTypeMapping]
    organization: Optional[ReadonlyOrganization] = None