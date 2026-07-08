from posthog.api.routing import RouterRegistry

from products.data_modeling.backend.presentation.views import DAGViewSet, EdgeViewSet, NodeViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"data_modeling_dags", DAGViewSet, "project_data_modeling_dags", ["team_id"])
    routers.register_legacy_dual_route(r"data_modeling_nodes", NodeViewSet, "project_data_modeling_nodes", ["team_id"])
    routers.register_legacy_dual_route(r"data_modeling_edges", EdgeViewSet, "project_data_modeling_edges", ["team_id"])
