from typing import Any, Optional
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.conf import settings

from .interfaces import (
    TeamProvider,
    SchemaProvider,
    CacheProvider,
    EntityProvider,
    ClickHouseProvider,
    MetricsProvider,
    ConfigProvider,
    TeamData,
    GroupTypeMappingData,
    DataWarehouseTableData,
    DataWarehouseSavedQueryData,
    DataWarehouseJoinData,
    ActionData,
    CohortData,
    PersonData,
)


class DjangoTeamProvider(TeamProvider):
    """Django-backed team provider implementation"""

    async def get_team(self, team_id: int) -> TeamData:
        from posthog.models import Team

        team = await sync_to_async(Team.objects.get)(pk=team_id)
        return TeamData(
            id=team.pk,
            pk=team.pk,
            project_id=team.project_id,
            organization_id=team.organization_id,
            api_token=team.api_token,
            timezone=team.timezone,
            week_start_day=team.week_start_day,
        )

    async def get_team_settings(self, team_id: int) -> dict[str, Any]:
        from posthog.models import Team

        team = await sync_to_async(Team.objects.get)(pk=team_id)
        return {
            "timezone": team.timezone,
            "week_start_day": team.week_start_day,
            "revenue_analytics_config": team.revenue_analytics_config.to_cache_key_dict()
            if hasattr(team, "revenue_analytics_config")
            else {},
            "marketing_analytics_config": team.marketing_analytics_config.to_cache_key_dict()
            if hasattr(team, "marketing_analytics_config")
            else {},
        }


class DjangoSchemaProvider(SchemaProvider):
    """Django-backed schema provider implementation"""

    async def get_group_mappings(self, project_id: int) -> list[GroupTypeMappingData]:
        from posthog.models.group_type_mapping import GroupTypeMapping

        mappings = await sync_to_async(list)(GroupTypeMapping.objects.filter(project_id=project_id))

        return [
            GroupTypeMappingData(
                group_type_index=mapping.group_type_index,
                group_type=mapping.group_type,
                project_id=mapping.project_id,
                created_at=mapping.created_at,
            )
            for mapping in mappings
        ]

    async def get_warehouse_tables(self, team_id: int) -> list[DataWarehouseTableData]:
        from posthog.warehouse.models.table import DataWarehouseTable

        tables = await sync_to_async(list)(
            DataWarehouseTable.objects.filter(team_id=team_id, deleted=False).select_related(
                "credential", "external_data_source"
            )
        )

        result = []
        for table in tables:
            external_data_source = None
            if table.external_data_source:
                external_data_source = {
                    "source_type": table.external_data_source.source_type,
                    "prefix": table.external_data_source.prefix,
                    "status": table.external_data_source.status,
                }

            credential = None
            if table.credential:
                credential = {
                    "access_key": getattr(table.credential, "access_key", None),
                    "access_secret": getattr(table.credential, "access_secret", None),
                }

            result.append(
                DataWarehouseTableData(
                    id=str(table.id),
                    name=table.name,
                    team_id=table.team_id,
                    format=table.format,
                    url_pattern=table.url_pattern,
                    row_count=table.row_count,
                    deleted=table.deleted,
                    columns=table.columns,
                    external_data_source=external_data_source,
                    credential=credential,
                )
            )

        return result

    async def get_saved_queries(self, team_id: int) -> list[DataWarehouseSavedQueryData]:
        from posthog.warehouse.models import DataWarehouseSavedQuery

        queries = await sync_to_async(list)(
            DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).select_related("table")
        )

        return [
            DataWarehouseSavedQueryData(
                id=str(query.pk),
                name=query.name,
                query=query.query,
                team_id=query.team_id,
                deleted=query.deleted,
                table={"row_count": query.table.row_count} if query.table else None,
            )
            for query in queries
        ]

    async def get_warehouse_joins(self, team_id: int) -> list[DataWarehouseJoinData]:
        from posthog.warehouse.models import DataWarehouseJoin

        joins = await sync_to_async(list)(DataWarehouseJoin.objects.filter(team_id=team_id).exclude(deleted=True))

        return [
            DataWarehouseJoinData(
                id=str(join.id),
                source_table_name=join.source_table_name,
                source_table_key=join.source_table_key,
                joining_table_name=join.joining_table_name,
                joining_table_key=join.joining_table_key,
                field_name=join.field_name,
                team_id=join.team_id,
                configuration=join.configuration or {},
                deleted=join.deleted,
            )
            for join in joins
        ]


class DjangoCacheProvider(CacheProvider):
    """Django-backed cache provider implementation"""

    async def get(self, key: str) -> Optional[Any]:
        return await sync_to_async(cache.get)(key)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await sync_to_async(cache.set)(key, value, ttl_seconds)

    async def delete(self, key: str) -> None:
        await sync_to_async(cache.delete)(key)

    async def exists(self, key: str) -> bool:
        return await sync_to_async(cache.has_key)(key)


class DjangoEntityProvider(EntityProvider):
    """Django-backed entity provider implementation"""

    async def get_action(self, action_id: int, project_id: int) -> ActionData:
        from posthog.models import Action

        action = await sync_to_async(Action.objects.get)(pk=action_id, team__project_id=project_id)

        return ActionData(id=action.pk, name=action.name, team_id=action.team_id, project_id=project_id)

    async def get_cohort(self, cohort_id: int, team_id: int) -> CohortData:
        from posthog.models import Cohort

        cohort = await sync_to_async(Cohort.objects.get)(pk=cohort_id, team_id=team_id)

        return CohortData(id=cohort.pk, name=cohort.name, team_id=cohort.team_id, is_static=cohort.is_static)

    async def get_person(self, person_id: str, team_id: int) -> PersonData:
        from posthog.models import Person

        # This is a simplified implementation
        # In reality, person lookup might be more complex
        person = await sync_to_async(Person.objects.get)(pk=person_id, team_id=team_id)

        return PersonData(
            id=str(person.pk),
            team_id=person.team_id,
            distinct_ids=[],  # Would need to fetch from ClickHouse
        )


class DjangoClickHouseProvider(ClickHouseProvider):
    """Django-backed ClickHouse provider implementation"""

    async def execute_query(
        self, query: str, parameters: Optional[dict[str, Any]] = None, workload: Optional[str] = None
    ) -> dict[str, Any]:
        from posthog.client import sync_execute

        # Convert to async execution
        result = await sync_to_async(sync_execute)(query, parameters or {}, workload=workload)

        return {
            "results": result,
            "columns": [],  # Would extract from result metadata
            "types": [],  # Would extract from result metadata
        }

    async def execute_query_with_progress(self, query: str, parameters: Optional[dict[str, Any]] = None) -> Any:
        # For now, just execute normally
        # In the future, this could support progress tracking
        return await self.execute_query(query, parameters)


class DjangoMetricsProvider(MetricsProvider):
    """Django-backed metrics provider implementation"""

    async def increment_counter(self, name: str, labels: dict[str, str], value: float = 1.0) -> None:
        # Import Prometheus metrics when needed
        try:
            import importlib.util

            if importlib.util.find_spec("prometheus_client"):
                # This would need to be handled properly with metric registration
                # For now, just a placeholder
                pass
        except ImportError:
            pass

    async def observe_histogram(self, name: str, labels: dict[str, str], value: float) -> None:
        try:
            import importlib.util

            if importlib.util.find_spec("prometheus_client"):
                # Placeholder for histogram observation
                pass
        except ImportError:
            pass

    async def record_query_timing(self, query_type: str, duration_seconds: float, team_id: int) -> None:
        # Record query timing - could use existing metrics or create new ones
        await self.observe_histogram(
            "hogql_query_duration_seconds", {"query_type": query_type, "team_id": str(team_id)}, duration_seconds
        )


class DjangoConfigProvider(ConfigProvider):
    """Django-backed configuration provider implementation"""

    async def get_feature_flag(self, flag_name: str, team_id: int, user_id: Optional[str] = None) -> bool:
        # This would integrate with PostHog's feature flag system
        # For now, return False as default
        return False

    async def get_setting(self, setting_name: str, default: Any = None) -> Any:
        return getattr(settings, setting_name, default)


def create_django_data_context():
    """Factory function to create Django-backed data context"""
    from .interfaces import HogQLDataContext

    return HogQLDataContext(
        team_provider=DjangoTeamProvider(),
        schema_provider=DjangoSchemaProvider(),
        cache_provider=DjangoCacheProvider(),
        entity_provider=DjangoEntityProvider(),
        clickhouse_provider=DjangoClickHouseProvider(),
        metrics_provider=DjangoMetricsProvider(),
        config_provider=DjangoConfigProvider(),
    )
