from posthog.api.routing import RouterRegistry

from products.data_modeling.backend.presentation.views import DAGViewSet, EdgeViewSet, NodeViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"data_modeling_dags", DAGViewSet, "project_data_modeling_dags", ["team_id"])
    routers.projects.register(r"data_modeling_nodes", NodeViewSet, "project_data_modeling_nodes", ["team_id"])
    routers.projects.register(r"data_modeling_edges", EdgeViewSet, "project_data_modeling_edges", ["team_id"])
