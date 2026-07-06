from posthog.api.routing import RouterRegistry

import products.data_warehouse.backend.presentation.views.fix_hogql as fix_hogql
from products.data_warehouse.backend.presentation.views import (
    column_annotation,
    column_statistics,
    data_modeling_job,
    data_warehouse,
    external_data_schema,
    external_data_source,
    managed_viewset,
    modeling,
    query_tab_state,
    saved_query,
    saved_query_column_annotation,
    saved_query_draft,
    table,
    view_link,
)
from products.data_warehouse.backend.presentation.views.lineage import LineageViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(
        r"warehouse_tables", table.TableViewSet, "environment_warehouse_tables", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"warehouse_saved_query_folders",
        saved_query.DataWarehouseSavedQueryFolderViewSet,
        "environment_warehouse_saved_query_folders",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"warehouse_saved_queries",
        saved_query.DataWarehouseSavedQueryViewSet,
        "environment_warehouse_saved_queries",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"warehouse_view_links", view_link.ViewLinkViewSet, "environment_warehouse_view_links", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"warehouse_view_link", view_link.ViewLinkViewSet, "environment_warehouse_view_link", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"external_data_sources",
        external_data_source.ExternalDataSourceViewSet,
        "environment_external_data_sources",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"data_warehouse", data_warehouse.DataWarehouseViewSet, "environment_data_warehouse", ["team_id"]
    )
    routers.projects.register(
        r"warehouse_dag", modeling.DataWarehouseModelDagViewSet, "project_warehouse_dag", ["team_id"]
    )
    routers.projects.register(
        r"warehouse_model_paths", modeling.DataWarehouseModelPathViewSet, "project_warehouse_model_paths", ["team_id"]
    )
    routers.projects.register(
        r"query_tab_state", query_tab_state.QueryTabStateViewSet, "project_query_tab_state", ["project_id"]
    )
    routers.register_legacy_dual_route(
        r"external_data_schemas",
        external_data_schema.ExternalDataSchemaViewset,
        "environment_external_data_schemas",
        ["team_id"],
    )
    routers.register_legacy_dual_route(r"fix_hogql", fix_hogql.FixHogQLViewSet, "project_fix_hogql", ["team_id"])
    routers.register_legacy_dual_route(
        r"warehouse_saved_query_drafts",
        saved_query_draft.DataWarehouseSavedQueryDraftViewSet,
        "project_warehouse_saved_query_drafts",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"managed_viewsets",
        managed_viewset.DataWarehouseManagedViewSetViewSet,
        "project_managed_viewsets",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"data_modeling_jobs", data_modeling_job.DataModelingJobViewSet, "environment_data_modeling_jobs", ["team_id"]
    )
    routers.register_legacy_dual_route(r"lineage", LineageViewSet, "project_lineage", ["team_id"])
    routers.projects.register(
        r"warehouse_column_annotations",
        column_annotation.WarehouseColumnAnnotationViewSet,
        "project_warehouse_column_annotations",
        ["team_id"],
    )
    routers.projects.register(
        r"saved_query_column_annotations",
        saved_query_column_annotation.DataWarehouseSavedQueryColumnAnnotationViewSet,
        "project_saved_query_column_annotations",
        ["team_id"],
    )
    routers.projects.register(
        r"warehouse_column_statistics",
        column_statistics.WarehouseColumnStatisticsViewSet,
        "project_warehouse_column_statistics",
        ["team_id"],
    )
