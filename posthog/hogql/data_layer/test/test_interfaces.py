import pytest
from unittest.mock import Mock
from datetime import datetime
from typing import Any, Optional

from ..interfaces import (
    TeamProvider,
    SchemaProvider,
    CacheProvider,
    TeamData,
    GroupTypeMappingData,
    DataWarehouseTableData,
    DataWarehouseSavedQueryData,
    DataWarehouseJoinData,
    HogQLDataContext,
)


class MockTeamProvider(TeamProvider):
    """Mock implementation for testing"""

    def __init__(self):
        self.teams = {}
        self.settings = {}

    async def get_team(self, team_id: int) -> TeamData:
        if team_id not in self.teams:
            raise ValueError(f"Team {team_id} not found")
        return self.teams[team_id]

    async def get_team_settings(self, team_id: int) -> dict[str, Any]:
        return self.settings.get(team_id, {})


class MockSchemaProvider(SchemaProvider):
    """Mock implementation for testing"""

    def __init__(self):
        self.group_mappings = {}
        self.warehouse_tables = {}
        self.saved_queries = {}
        self.warehouse_joins = {}

    async def get_group_mappings(self, project_id: int) -> list[GroupTypeMappingData]:
        return self.group_mappings.get(project_id, [])

    async def get_warehouse_tables(self, team_id: int) -> list[DataWarehouseTableData]:
        return self.warehouse_tables.get(team_id, [])

    async def get_saved_queries(self, team_id: int) -> list[DataWarehouseSavedQueryData]:
        return self.saved_queries.get(team_id, [])

    async def get_warehouse_joins(self, team_id: int) -> list[DataWarehouseJoinData]:
        return self.warehouse_joins.get(team_id, [])


class MockCacheProvider(CacheProvider):
    """Mock implementation for testing"""

    def __init__(self):
        self.cache = {}

    async def get(self, key: str) -> Optional[Any]:
        return self.cache.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.cache[key] = value

    async def delete(self, key: str) -> None:
        self.cache.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.cache


@pytest.mark.asyncio
class TestTeamProvider:
    """Test team provider interface"""

    async def test_mock_team_provider(self):
        provider = MockTeamProvider()

        # Test team not found
        with pytest.raises(ValueError, match="Team 1 not found"):
            await provider.get_team(1)

        # Add team data
        team_data = TeamData(
            id=1, pk=1, project_id=100, organization_id=1000, api_token="test-token", timezone="UTC", week_start_day=1
        )
        provider.teams[1] = team_data

        # Test successful retrieval
        result = await provider.get_team(1)
        assert result.id == 1
        assert result.api_token == "test-token"
        assert result.timezone == "UTC"

        # Test settings
        provider.settings[1] = {"test_setting": "value"}
        settings = await provider.get_team_settings(1)
        assert settings["test_setting"] == "value"


@pytest.mark.asyncio
class TestSchemaProvider:
    """Test schema provider interface"""

    async def test_mock_schema_provider(self):
        provider = MockSchemaProvider()

        # Test empty results
        mappings = await provider.get_group_mappings(100)
        assert mappings == []

        tables = await provider.get_warehouse_tables(1)
        assert tables == []

        # Add test data
        mapping = GroupTypeMappingData(
            group_type_index=0, group_type="company", project_id=100, created_at=datetime.now()
        )
        provider.group_mappings[100] = [mapping]

        table = DataWarehouseTableData(
            id="table-1", name="test_table", team_id=1, format="Parquet", url_pattern="s3://bucket/path", row_count=1000
        )
        provider.warehouse_tables[1] = [table]

        # Test retrieval
        result_mappings = await provider.get_group_mappings(100)
        assert len(result_mappings) == 1
        assert result_mappings[0].group_type == "company"

        result_tables = await provider.get_warehouse_tables(1)
        assert len(result_tables) == 1
        assert result_tables[0].name == "test_table"
        assert result_tables[0].row_count == 1000


@pytest.mark.asyncio
class TestCacheProvider:
    """Test cache provider interface"""

    async def test_mock_cache_provider(self):
        provider = MockCacheProvider()

        # Test cache miss
        result = await provider.get("nonexistent")
        assert result is None

        exists = await provider.exists("nonexistent")
        assert not exists

        # Test cache set/get
        await provider.set("test_key", {"data": "value"}, 300)

        result = await provider.get("test_key")
        assert result == {"data": "value"}

        exists = await provider.exists("test_key")
        assert exists

        # Test cache delete
        await provider.delete("test_key")
        result = await provider.get("test_key")
        assert result is None


class TestDataStructures:
    """Test data structure classes"""

    def test_team_data(self):
        team = TeamData(
            id=1, pk=1, project_id=100, organization_id=1000, api_token="token", timezone="America/New_York"
        )

        assert team.id == 1
        assert team.timezone == "America/New_York"
        assert team.week_start_day is None  # Optional field

    def test_group_type_mapping_data(self):
        now = datetime.now()
        mapping = GroupTypeMappingData(group_type_index=0, group_type="organization", project_id=123, created_at=now)

        assert mapping.group_type_index == 0
        assert mapping.group_type == "organization"
        assert mapping.created_at == now

    def test_warehouse_table_data(self):
        table = DataWarehouseTableData(
            id="uuid-123",
            name="customers",
            team_id=1,
            format="Parquet",
            url_pattern="s3://data/customers/*",
            row_count=50000,
            columns={"id": "String", "name": "String"},
        )

        assert table.id == "uuid-123"
        assert table.name == "customers"
        assert table.row_count == 50000
        assert table.columns["id"] == "String"
        assert not table.deleted  # Default value


class TestHogQLDataContext:
    """Test the data context container"""

    def test_data_context_creation(self):
        team_provider = MockTeamProvider()
        schema_provider = MockSchemaProvider()
        cache_provider = MockCacheProvider()
        entity_provider = Mock()
        clickhouse_provider = Mock()
        metrics_provider = Mock()
        config_provider = Mock()

        context = HogQLDataContext(
            team_provider=team_provider,
            schema_provider=schema_provider,
            cache_provider=cache_provider,
            entity_provider=entity_provider,
            clickhouse_provider=clickhouse_provider,
            metrics_provider=metrics_provider,
            config_provider=config_provider,
        )

        assert isinstance(context.team_provider, MockTeamProvider)
        assert isinstance(context.schema_provider, MockSchemaProvider)
        assert isinstance(context.cache_provider, MockCacheProvider)
        assert context.entity_provider is not None
        assert context.clickhouse_provider is not None
        assert context.metrics_provider is not None
        assert context.config_provider is not None


@pytest.mark.asyncio
class TestProviderInteractionPatterns:
    """Test common patterns of provider interactions"""

    async def test_team_and_schema_interaction(self):
        team_provider = MockTeamProvider()
        schema_provider = MockSchemaProvider()

        # Setup test data
        team_data = TeamData(id=1, pk=1, project_id=100, organization_id=1000, api_token="token")
        team_provider.teams[1] = team_data

        mapping = GroupTypeMappingData(
            group_type_index=0, group_type="company", project_id=100, created_at=datetime.now()
        )
        schema_provider.group_mappings[100] = [mapping]

        # Test workflow: get team, then get schema for that team's project
        team = await team_provider.get_team(1)
        mappings = await schema_provider.get_group_mappings(team.project_id)

        assert len(mappings) == 1
        assert mappings[0].group_type == "company"
        assert mappings[0].project_id == team.project_id

    async def test_cache_workflow(self):
        cache_provider = MockCacheProvider()

        # Simulate caching workflow
        cache_key = "team:1:schema"

        # Check cache miss
        cached_data = await cache_provider.get(cache_key)
        assert cached_data is None

        # Simulate data computation and caching
        computed_data = {"tables": ["events", "persons"], "computed_at": "2024-01-01"}
        await cache_provider.set(cache_key, computed_data, 3600)

        # Verify cache hit
        cached_data = await cache_provider.get(cache_key)
        assert cached_data == computed_data
        assert cached_data["tables"] == ["events", "persons"]
