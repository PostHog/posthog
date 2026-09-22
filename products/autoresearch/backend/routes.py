from posthog.api.routing import RouterRegistry

import products.autoresearch.backend.presentation.views.views as autoresearch


def register_routes(routers: RouterRegistry) -> None:
    autoresearch_router = routers.projects.register(
        r"autoresearch",
        autoresearch.AutoresearchPipelineViewSet,
        "project_autoresearch_pipelines",
        ["project_id"],
    )
    autoresearch_router.register(
        r"models",
        autoresearch.AutoresearchModelViewSet,
        "project_autoresearch_models",
        ["project_id", "pipeline_id"],
    )
    autoresearch_router.register(
        r"runs",
        autoresearch.AutoresearchRunViewSet,
        "project_autoresearch_runs",
        ["project_id", "pipeline_id"],
    )
    autoresearch_router.register(
        r"training_runs",
        autoresearch.AutoresearchTrainingRunViewSet,
        "project_autoresearch_training_runs",
        ["project_id", "pipeline_id"],
    )
