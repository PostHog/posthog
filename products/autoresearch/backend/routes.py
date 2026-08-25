from posthog.api.routing import RouterRegistry

import products.autoresearch.backend.presentation.views.views as autoresearch


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"autoresearch",
        autoresearch.AutoresearchPipelineViewSet,
        "project_autoresearch_pipelines",
        ["project_id"],
    )
