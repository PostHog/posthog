from posthog.api.routing import RouterRegistry

import products.data_warehouse.backend.presentation.views.fix_hogql as fix_hogql
from products.data_warehouse.backend.presentation.views import (
    column_annotation,
    data_modeling_job,
    data_warehouse,
    expression,
    managed_viewset,
    query_tab_state,
    saved_query_column_annotation,
    saved_query_draft,
    table,
    view_link,
)
from products.data_warehouse.backend.presentation.views.saved_query import (
    folders as saved_query_folders,
    viewset as saved_query_viewset,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"warehouse_tables", table.TableViewSet, "project_warehouse_tables", ["team_id"])
    routers.projects.register(
        r"warehouse_saved_query_folders",
        saved_query_folders.DataWarehouseSavedQueryFolderViewSet,
        "project_warehouse_saved_query_folders",
        ["team_id"],
    )
    routers.projects.register(
        r"warehouse_saved_queries",
        saved_query_viewset.DataWarehouseSavedQueryViewSet,
        "project_warehouse_saved_queries",
        ["team_id"],
    )
    routers.projects.register(
        r"warehouse_view_links", view_link.ViewLinkViewSet, "project_warehouse_view_links", ["team_id"]
    )
    routers.projects.register(
        r"warehouse_view_link", view_link.ViewLinkViewSet, "project_warehouse_view_link", ["team_id"]
    )
    routers.projects.register(
        r"warehouse_expressions",
        expression.DataWarehouseExpressionViewSet,
        "project_warehouse_expressions",
        ["team_id"],
    )
    routers.projects.register(
        r"data_warehouse", data_warehouse.DataWarehouseViewSet, "project_data_warehouse", ["team_id"]
    )
    routers.projects.register(
        r"query_tab_state", query_tab_state.QueryTabStateViewSet, "project_query_tab_state", ["project_id"]
    )
    routers.projects.register(r"fix_hogql", fix_hogql.FixHogQLViewSet, "project_fix_hogql", ["team_id"])
    routers.projects.register(
        r"warehouse_saved_query_drafts",
        saved_query_draft.DataWarehouseSavedQueryDraftViewSet,
        "project_warehouse_saved_query_drafts",
        ["team_id"],
    )
    routers.projects.register(
        r"managed_viewsets",
        managed_viewset.DataWarehouseManagedViewSetViewSet,
        "project_managed_viewsets",
        ["team_id"],
    )
    routers.projects.register(
        r"data_modeling_jobs", data_modeling_job.DataModelingJobViewSet, "project_data_modeling_jobs", ["team_id"]
    )
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
