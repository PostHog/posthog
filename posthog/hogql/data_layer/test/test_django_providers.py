import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from ..django_providers import (
    DjangoTeamProvider,
    DjangoSchemaProvider,
    DjangoCacheProvider,
    DjangoEntityProvider,
    DjangoClickHouseProvider,
    DjangoMetricsProvider,
    DjangoConfigProvider,
    create_django_data_context,
)
from ..interfaces import TeamData, GroupTypeMappingData


@pytest.mark.asyncio
class TestDjangoTeamProvider:
    """Test Django team provider implementation"""

    @patch("posthog.models.Team.objects.get")
    async def test_get_team(self, mock_get):
        # Setup mock team
        mock_team = Mock()
        mock_team.pk = 1
        mock_team.project_id = 100
        mock_team.organization_id = 1000
        mock_team.api_token = "test-token"
        mock_team.timezone = "UTC"
        mock_team.week_start_day = 1
        mock_get.return_value = mock_team

        provider = DjangoTeamProvider()

        with patch("asgiref.sync.sync_to_async") as mock_sync_to_async:
            mock_sync_to_async.return_value = mock_team

            result = await provider.get_team(1)

            assert isinstance(result, TeamData)
            assert result.id == 1
            assert result.pk == 1
            assert result.project_id == 100
            assert result.api_token == "test-token"
            assert result.timezone == "UTC"

    @patch("posthog.models.Team.objects.get")
    async def test_get_team_settings(self, mock_get):
        # Setup mock team with analytics configs
        mock_team = Mock()
        mock_team.timezone = "America/New_York"
        mock_team.week_start_day = 0

        # Mock analytics configs
        mock_revenue_config = Mock()
        mock_revenue_config.to_cache_key_dict.return_value = {"revenue": "config"}
        mock_team.revenue_analytics_config = mock_revenue_config

        mock_marketing_config = Mock()
        mock_marketing_config.to_cache_key_dict.return_value = {"marketing": "config"}
        mock_team.marketing_analytics_config = mock_marketing_config

        mock_get.return_value = mock_team

        provider = DjangoTeamProvider()

        with patch("asgiref.sync.sync_to_async") as mock_sync_to_async:
            mock_sync_to_async.return_value = mock_team

            result = await provider.get_team_settings(1)

            assert result["timezone"] == "America/New_York"
            assert result["week_start_day"] == 0
            assert result["revenue_analytics_config"] == {"revenue": "config"}
            assert result["marketing_analytics_config"] == {"marketing": "config"}


@pytest.mark.asyncio
class TestDjangoSchemaProvider:
    """Test Django schema provider implementation"""

    async def test_get_group_mappings(self):
        # Setup mock mappings
        mock_mapping = Mock()
        mock_mapping.group_type_index = 0
        mock_mapping.group_type = "company"
        mock_mapping.project_id = 100
        mock_mapping.created_at = datetime.now()

        provider = DjangoSchemaProvider()

        with patch("posthog.models.group_type_mapping.GroupTypeMapping.objects.filter") as mock_filter:
            mock_filter.return_value = [mock_mapping]

            with patch("asgiref.sync.sync_to_async") as mock_sync_to_async:
                mock_sync_to_async.return_value = [mock_mapping]

                result = await provider.get_group_mappings(100)

                assert len(result) == 1
                assert isinstance(result[0], GroupTypeMappingData)
                assert result[0].group_type_index == 0
                assert result[0].group_type == "company"
                assert result[0].project_id == 100

    async def test_get_warehouse_tables(self):
        # Setup mock table
        mock_table = Mock()
        mock_table.id = "table-uuid"
        mock_table.name = "customers"
        mock_table.team_id = 1
        mock_table.format = "Parquet"
        mock_table.url_pattern = "s3://bucket/customers/*"
        mock_table.row_count = 1000
        mock_table.deleted = False
        mock_table.columns = {"id": "String", "name": "String"}

        # Mock external data source
        mock_external_source = Mock()
        mock_external_source.source_type = "S3"
        mock_external_source.prefix = "prod"
        mock_external_source.status = "completed"
        mock_table.external_data_source = mock_external_source

        # Mock credential
        mock_credential = Mock()
        mock_credential.access_key = "ACCESS_KEY"
        mock_credential.access_secret = "SECRET"
        mock_table.credential = mock_credential

        provider = DjangoSchemaProvider()

        with patch("posthog.warehouse.models.table.DataWarehouseTable.objects.filter") as mock_filter:
            mock_queryset = Mock()
            mock_queryset.select_related.return_value = [mock_table]
            mock_filter.return_value = mock_queryset

            with patch("asgiref.sync.sync_to_async") as mock_sync_to_async:
                mock_sync_to_async.return_value = [mock_table]

                result = await provider.get_warehouse_tables(1)

                assert len(result) == 1
                table = result[0]
                assert table.id == "table-uuid"
                assert table.name == "customers"
                assert table.format == "Parquet"
                assert table.external_data_source["source_type"] == "S3"
                assert table.credential["access_key"] == "ACCESS_KEY"


@pytest.mark.asyncio
class TestDjangoCacheProvider:
    """Test Django cache provider implementation"""

    async def test_cache_operations(self):
        provider = DjangoCacheProvider()

        # Mock the imported cache object and sync_to_async
        with patch("posthog.hogql.data_layer.django_providers.cache"):
            with patch("posthog.hogql.data_layer.django_providers.sync_to_async") as mock_sync_to_async:
                # Mock get operation
                async def mock_get_async(key):
                    return {"test": "data"}

                mock_sync_to_async.return_value = mock_get_async

                result = await provider.get("test_key")
                assert result == {"test": "data"}

                # Mock set operation
                async def mock_set_async(key, value, ttl):
                    return None

                mock_sync_to_async.return_value = mock_set_async

                await provider.set("test_key", {"new": "data"}, 300)

                # Mock delete operation
                async def mock_delete_async(key):
                    return None

                mock_sync_to_async.return_value = mock_delete_async

                await provider.delete("test_key")

                # Mock exists operation
                async def mock_exists_async(key):
                    return True

                mock_sync_to_async.return_value = mock_exists_async

                result = await provider.exists("test_key")
                assert result is True


@pytest.mark.asyncio
class TestDjangoEntityProvider:
    """Test Django entity provider implementation"""

    async def test_get_action(self):
        # Setup mock action
        mock_action = Mock()
        mock_action.pk = 123
        mock_action.name = "Sign Up"
        mock_action.team_id = 1

        provider = DjangoEntityProvider()

        with patch("posthog.models.Action.objects.get") as mock_get:
            mock_get.return_value = mock_action

            with patch("asgiref.sync.sync_to_async") as mock_sync_to_async:
                mock_sync_to_async.return_value = mock_action

                result = await provider.get_action(123, 100)

                assert result.id == 123
                assert result.name == "Sign Up"
                assert result.team_id == 1
                assert result.project_id == 100

    async def test_get_cohort(self):
        # Setup mock cohort
        mock_cohort = Mock()
        mock_cohort.pk = 456
        mock_cohort.name = "Power Users"
        mock_cohort.team_id = 1
        mock_cohort.is_static = True

        provider = DjangoEntityProvider()

        with patch("posthog.models.Cohort.objects.get") as mock_get:
            mock_get.return_value = mock_cohort

            with patch("asgiref.sync.sync_to_async") as mock_sync_to_async:
                mock_sync_to_async.return_value = mock_cohort

                result = await provider.get_cohort(456, 1)

                assert result.id == 456
                assert result.name == "Power Users"
                assert result.is_static is True


@pytest.mark.asyncio
class TestDjangoClickHouseProvider:
    """Test Django ClickHouse provider implementation"""

    async def test_execute_query(self):
        provider = DjangoClickHouseProvider()

        # Mock query result
        mock_result = [("value1", 123), ("value2", 456)]

        with patch("posthog.hogql.data_layer.django_providers.sync_to_async") as mock_sync_to_async:
            with patch("posthog.client.sync_execute") as mock_execute:
                # Mock sync_to_async to return an async function that calls sync_execute
                async def mock_async_execute(query, params, workload=None):
                    return mock_execute(query, params, workload=workload)

                mock_sync_to_async.return_value = mock_async_execute
                mock_execute.return_value = mock_result

                result = await provider.execute_query("SELECT * FROM events", {"team_id": 1}, workload="analytics")

                assert result["results"] == mock_result
                assert "columns" in result
                assert "types" in result


@pytest.mark.asyncio
class TestDjangoConfigProvider:
    """Test Django config provider implementation"""

    async def test_get_setting(self):
        provider = DjangoConfigProvider()

        # Mock settings object
        mock_settings = Mock()
        mock_settings.DEBUG = True
        mock_settings.SECRET_KEY = "test-secret"

        # Mock getattr to simulate settings behavior
        original_getattr = getattr

        def mock_getattr(obj, name, default=None):
            if obj is mock_settings:
                if hasattr(obj, name):
                    return original_getattr(obj, name)
                else:
                    return default
            return original_getattr(obj, name, default)

        with patch("posthog.hogql.data_layer.django_providers.settings", mock_settings):
            with patch("builtins.getattr", side_effect=mock_getattr):
                # Test existing setting
                result = await provider.get_setting("DEBUG")
                assert result is True

                # Test setting with default
                result = await provider.get_setting("NONEXISTENT", "default_value")
                assert result == "default_value"

    async def test_get_feature_flag(self):
        provider = DjangoConfigProvider()

        # For now, feature flags return False by default
        result = await provider.get_feature_flag("test_flag", 1, "user123")
        assert result is False


class TestFactoryFunction:
    """Test the Django data context factory"""

    def test_create_django_data_context(self):
        context = create_django_data_context()

        # Verify all providers are Django implementations
        assert isinstance(context.team_provider, DjangoTeamProvider)
        assert isinstance(context.schema_provider, DjangoSchemaProvider)
        assert isinstance(context.cache_provider, DjangoCacheProvider)
        assert isinstance(context.entity_provider, DjangoEntityProvider)
        assert isinstance(context.clickhouse_provider, DjangoClickHouseProvider)
        assert isinstance(context.metrics_provider, DjangoMetricsProvider)
        assert isinstance(context.config_provider, DjangoConfigProvider)


@pytest.mark.asyncio
class TestProviderIntegration:
    """Test integration between Django providers"""

    async def test_team_to_schema_workflow(self):
        """Test getting team data and using it to fetch schema"""
        team_provider = DjangoTeamProvider()
        schema_provider = DjangoSchemaProvider()

        # Mock team
        mock_team = Mock()
        mock_team.pk = 1
        mock_team.project_id = 100
        mock_team.organization_id = 1000
        mock_team.api_token = "token"
        mock_team.timezone = None
        mock_team.week_start_day = None

        # Mock group mapping
        mock_mapping = Mock()
        mock_mapping.group_type_index = 0
        mock_mapping.group_type = "organization"
        mock_mapping.project_id = 100
        mock_mapping.created_at = datetime.now()

        with patch("posthog.models.Team.objects.get", return_value=mock_team):
            with patch("posthog.models.group_type_mapping.GroupTypeMapping.objects.filter") as mock_filter:
                mock_filter.return_value = [mock_mapping]

                with patch("asgiref.sync.sync_to_async", side_effect=lambda f: f):
                    # Get team first
                    team = await team_provider.get_team(1)

                    # Then get schema for team's project
                    mappings = await schema_provider.get_group_mappings(team.project_id)

                    assert team.project_id == 100
                    assert len(mappings) == 1
                    assert mappings[0].project_id == team.project_id
