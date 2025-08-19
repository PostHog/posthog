from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class TeamData:
    """Team data structure for HogQL operations"""

    id: int
    pk: int
    project_id: int
    organization_id: int
    api_token: str
    timezone: Optional[str] = None
    week_start_day: Optional[int] = None


@dataclass
class GroupTypeMappingData:
    """Group type mapping data structure"""

    group_type_index: int
    group_type: str
    project_id: int
    created_at: datetime


@dataclass
class DataWarehouseTableData:
    """Data warehouse table data structure"""

    id: str
    name: str
    team_id: int
    format: Optional[str] = None
    url_pattern: Optional[str] = None
    row_count: Optional[int] = None
    deleted: bool = False
    columns: Optional[dict[str, Any]] = None
    external_data_source: Optional[dict[str, Any]] = None
    credential: Optional[dict[str, Any]] = None


@dataclass
class DataWarehouseSavedQueryData:
    """Data warehouse saved query data structure"""

    id: str
    name: str
    query: dict[str, Any]
    team_id: int
    deleted: bool = False
    table: Optional[dict[str, Any]] = None


@dataclass
class DataWarehouseJoinData:
    """Data warehouse join data structure"""

    id: str
    source_table_name: str
    source_table_key: str
    joining_table_name: str
    joining_table_key: str
    field_name: str
    team_id: int
    configuration: dict[str, Any]
    deleted: bool = False


@dataclass
class ActionData:
    """Action data structure"""

    id: int
    name: str
    team_id: int
    project_id: int


@dataclass
class CohortData:
    """Cohort data structure"""

    id: int
    name: str
    team_id: int
    is_static: bool


@dataclass
class PersonData:
    """Person data structure"""

    id: str
    team_id: int
    distinct_ids: list[str]


class TeamProvider(ABC):
    """Abstract provider for team-related data operations"""

    @abstractmethod
    async def get_team(self, team_id: int) -> TeamData:
        """Get team data by ID"""
        pass

    @abstractmethod
    async def get_team_settings(self, team_id: int) -> dict[str, Any]:
        """Get team-specific configuration settings"""
        pass


class SchemaProvider(ABC):
    """Abstract provider for database schema operations"""

    @abstractmethod
    async def get_group_mappings(self, project_id: int) -> list[GroupTypeMappingData]:
        """Get group type mappings for a project"""
        pass

    @abstractmethod
    async def get_warehouse_tables(self, team_id: int) -> list[DataWarehouseTableData]:
        """Get data warehouse tables for a team"""
        pass

    @abstractmethod
    async def get_saved_queries(self, team_id: int) -> list[DataWarehouseSavedQueryData]:
        """Get saved queries for a team"""
        pass

    @abstractmethod
    async def get_warehouse_joins(self, team_id: int) -> list[DataWarehouseJoinData]:
        """Get data warehouse joins for a team"""
        pass


class CacheProvider(ABC):
    """Abstract provider for caching operations"""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get cached data by key"""
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Set cached data with TTL"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete cached data by key"""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        pass


class EntityProvider(ABC):
    """Abstract provider for PostHog entity operations"""

    @abstractmethod
    async def get_action(self, action_id: int, project_id: int) -> ActionData:
        """Get action data by ID and project"""
        pass

    @abstractmethod
    async def get_cohort(self, cohort_id: int, team_id: int) -> CohortData:
        """Get cohort data by ID and team"""
        pass

    @abstractmethod
    async def get_person(self, person_id: str, team_id: int) -> PersonData:
        """Get person data by ID and team"""
        pass


class ClickHouseProvider(ABC):
    """Abstract provider for ClickHouse operations"""

    @abstractmethod
    async def execute_query(
        self, query: str, parameters: Optional[dict[str, Any]] = None, workload: Optional[str] = None
    ) -> dict[str, Any]:
        """Execute ClickHouse query"""
        pass

    @abstractmethod
    async def execute_query_with_progress(self, query: str, parameters: Optional[dict[str, Any]] = None) -> Any:
        """Execute query with progress tracking"""
        pass


class MetricsProvider(ABC):
    """Abstract provider for metrics and monitoring"""

    @abstractmethod
    async def increment_counter(self, name: str, labels: dict[str, str], value: float = 1.0) -> None:
        """Increment a counter metric"""
        pass

    @abstractmethod
    async def observe_histogram(self, name: str, labels: dict[str, str], value: float) -> None:
        """Record histogram observation"""
        pass

    @abstractmethod
    async def record_query_timing(self, query_type: str, duration_seconds: float, team_id: int) -> None:
        """Record query execution timing"""
        pass


class ConfigProvider(ABC):
    """Abstract provider for configuration"""

    @abstractmethod
    async def get_feature_flag(self, flag_name: str, team_id: int, user_id: Optional[str] = None) -> bool:
        """Check feature flag value"""
        pass

    @abstractmethod
    async def get_setting(self, setting_name: str, default: Any = None) -> Any:
        """Get configuration setting"""
        pass


@dataclass
class HogQLDataContext:
    """Container for all data providers used by HogQL operations"""

    team_provider: TeamProvider
    schema_provider: SchemaProvider
    cache_provider: CacheProvider
    entity_provider: EntityProvider
    clickhouse_provider: ClickHouseProvider
    metrics_provider: MetricsProvider
    config_provider: ConfigProvider
