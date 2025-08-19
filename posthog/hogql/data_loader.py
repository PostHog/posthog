"""
Django-specific data loading functions for HogQL.

This module contains all Django ORM interactions needed to load data for HogQL operations.
The core HogQL logic should never import Django directly - it gets all data through HogQLDependencies.
"""

from .dependencies import (
    HogQLDependencies,
    TeamData,
    GroupTypeMappingData,
    DataWarehouseTableData,
    DataWarehouseSavedQueryData,
    DataWarehouseJoinData,
    ExternalDataJobData,
    RevenueAnalyticsViewData,
)


def load_team_data(team_id: int, team=None) -> TeamData:
    """Load team data from Django ORM"""
    if team is None:
        from posthog.models import Team

        team = Team.objects.get(pk=team_id)

    return TeamData(
        pk=team.pk,
        project_id=team.project_id,
        organization_id=team.organization_id,
        timezone=team.timezone,
        week_start_day=team.week_start_day,
        api_token=team.api_token,
        modifiers=team.modifiers or {},
        person_on_events_mode_flag_based_default=str(team.person_on_events_mode_flag_based_default),
    )


def load_group_mappings(project_id: int) -> list[GroupTypeMappingData]:
    """Load group type mappings from Django ORM"""
    from posthog.models.group_type_mapping import GroupTypeMapping

    mappings = GroupTypeMapping.objects.filter(project_id=project_id)

    return [
        GroupTypeMappingData(
            group_type_index=mapping.group_type_index, group_type=mapping.group_type, project_id=mapping.project_id
        )
        for mapping in mappings
    ]


def load_warehouse_tables(team_id: int) -> list[DataWarehouseTableData]:
    """Load data warehouse tables from Django ORM"""
    from posthog.warehouse.models.table import DataWarehouseTable

    tables = list(
        DataWarehouseTable.objects.filter(team_id=team_id)
        .exclude(deleted=True)
        .select_related("credential", "external_data_source")
        .prefetch_related("externaldataschema_set")
    )

    result = []
    for table in tables:
        # Serialize external data source
        external_data_source = None
        if table.external_data_source:
            external_data_source = {
                "source_id": str(table.external_data_source.source_id),
                "source_type": table.external_data_source.source_type,
                "prefix": table.external_data_source.prefix,
                "status": table.external_data_source.status,
            }

        # Serialize credential
        credential = None
        if table.credential:
            credential = {
                "access_key": getattr(table.credential, "access_key", None),
                "access_secret": getattr(table.credential, "access_secret", None),
            }

        # Serialize external data schemas
        external_data_schemas = []
        for schema in table.externaldataschema_set.all():
            external_data_schemas.append(
                {
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": schema.should_sync,
                    "is_incremental": schema.is_incremental,
                    "status": schema.status,
                    "last_synced_at": schema.last_synced_at.isoformat() if schema.last_synced_at else None,
                }
            )

        result.append(
            DataWarehouseTableData(
                id=str(table.id),
                name=table.name,
                team_id=table.team_id,
                deleted=table.deleted,
                format=table.format,
                url_pattern=table.url_pattern,
                row_count=table.row_count,
                columns=table.columns,
                external_data_source=external_data_source,
                credential=credential,
                external_data_schemas=external_data_schemas,
            )
        )

    return result


def load_saved_queries(team_id: int) -> list[DataWarehouseSavedQueryData]:
    """Load data warehouse saved queries from Django ORM"""
    from posthog.warehouse.models import DataWarehouseSavedQuery

    queries = list(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).select_related("table")
    )

    result = []
    for query in queries:
        # Serialize table data
        table = None
        if query.table:
            table = {
                "id": str(query.table.id),
                "row_count": query.table.row_count,
            }

        result.append(
            DataWarehouseSavedQueryData(
                pk=query.pk,
                name=query.name,
                query=query.query,
                team_id=query.team_id,
                deleted=query.deleted,
                columns=query.columns or {},
                table=table,
            )
        )

    return result


def load_warehouse_joins(team_id: int) -> list[DataWarehouseJoinData]:
    """Load data warehouse joins from Django ORM"""
    from posthog.warehouse.models import DataWarehouseJoin

    joins = list(DataWarehouseJoin.objects.filter(team_id=team_id).exclude(deleted=True))

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


def load_external_data_jobs(team_id: int) -> list[ExternalDataJobData]:
    """Load external data jobs from Django ORM"""
    from posthog.warehouse.models.external_data_job import ExternalDataJob

    # Get latest completed jobs for each source
    jobs = list(
        ExternalDataJob.objects.filter(status="Completed", team_id=team_id).order_by("-created_at")[
            :10
        ]  # Limit to recent jobs
    )

    return [ExternalDataJobData(id=str(job.id), status=job.status, created_at=job.created_at) for job in jobs]


def load_revenue_analytics_views(team) -> list[RevenueAnalyticsViewData]:
    """Load revenue analytics views"""
    try:
        from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views

        revenue_views = list(build_all_revenue_analytics_views(team, None))

        return [
            RevenueAnalyticsViewData(
                name=view.name,
                source_id=getattr(view, "source_id", ""),
                query=view.query if hasattr(view, "query") else "",
            )
            for view in revenue_views
        ]
    except Exception:
        # Revenue analytics might not be available
        return []


def load_hogql_dependencies(
    team_id: int, team=None, load_warehouse_data: bool = True, load_revenue_views: bool = True
) -> HogQLDependencies:
    """
    Load all dependencies needed for HogQL operations.

    This is the main entry point that Django code should use to prepare data for HogQL.
    """
    # Load core team data
    team_data = load_team_data(team_id, team)

    # Load schema data
    group_mappings = load_group_mappings(team_data.project_id)

    # Load warehouse data (can be disabled for performance)
    warehouse_tables = []
    saved_queries = []
    warehouse_joins = []
    external_data_jobs = []

    if load_warehouse_data:
        warehouse_tables = load_warehouse_tables(team_id)
        saved_queries = load_saved_queries(team_id)
        warehouse_joins = load_warehouse_joins(team_id)
        external_data_jobs = load_external_data_jobs(team_id)

    # Load revenue analytics views (can be disabled)
    revenue_views = []
    if load_revenue_views:
        revenue_views = load_revenue_analytics_views(team or team_data)

    return HogQLDependencies(
        team=team_data,
        group_mappings=group_mappings,
        warehouse_tables=warehouse_tables,
        saved_queries=saved_queries,
        warehouse_joins=warehouse_joins,
        external_data_jobs=external_data_jobs,
        revenue_views=revenue_views,
    )
