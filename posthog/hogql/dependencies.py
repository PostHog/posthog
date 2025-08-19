from dataclasses import dataclass
from typing import Optional, Any
from datetime import datetime


@dataclass
class TeamData:
    """Team data needed for HogQL operations"""

    pk: int
    project_id: int
    organization_id: int
    timezone: Optional[str]
    week_start_day: Optional[int]
    api_token: str
    modifiers: dict[str, Any]
    person_on_events_mode_flag_based_default: str  # PersonsOnEventsMode enum as string


@dataclass
class GroupTypeMappingData:
    """Group type mapping data"""

    group_type_index: int
    group_type: str
    project_id: int


@dataclass
class DataWarehouseTableData:
    """Data warehouse table data"""

    id: str
    name: str
    team_id: int
    deleted: bool
    format: Optional[str]
    url_pattern: Optional[str]
    row_count: Optional[int]
    columns: Optional[dict[str, Any]]
    # Related data
    external_data_source: Optional[dict[str, Any]]  # Serialized external data source
    credential: Optional[dict[str, Any]]  # Serialized credential
    external_data_schemas: list[dict[str, Any]]  # Serialized schemas


@dataclass
class DataWarehouseSavedQueryData:
    """Data warehouse saved query data"""

    pk: int
    name: str
    query: dict[str, Any]
    team_id: int
    deleted: bool
    columns: Optional[dict[str, Any]]  # Column definitions
    # Related data
    table: Optional[dict[str, Any]]  # Serialized table data


@dataclass
class DataWarehouseJoinData:
    """Data warehouse join data"""

    id: str
    source_table_name: str
    source_table_key: str
    joining_table_name: str
    joining_table_key: str
    field_name: str
    team_id: int
    configuration: dict[str, Any]
    deleted: bool


@dataclass
class ExternalDataJobData:
    """External data job data"""

    id: str
    status: str
    created_at: datetime


@dataclass
class RevenueAnalyticsViewData:
    """Revenue analytics view data"""

    name: str
    source_id: str
    query: str


@dataclass
class HogQLDependencies:
    """All data that HogQL needs, preloaded to avoid Django dependencies in core logic"""

    # Core team data
    team: TeamData

    # Schema-related data
    group_mappings: list[GroupTypeMappingData]

    # Data warehouse data
    warehouse_tables: list[DataWarehouseTableData]
    saved_queries: list[DataWarehouseSavedQueryData]
    warehouse_joins: list[DataWarehouseJoinData]

    # External data jobs (for latest completed jobs)
    external_data_jobs: list[ExternalDataJobData]

    # Revenue analytics views (if available)
    revenue_views: list[RevenueAnalyticsViewData]
