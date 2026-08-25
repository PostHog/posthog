from django.core.management.base import CommandError

from products.autoresearch.backend.models import AutoresearchPipeline


def resolve_pipeline(pipeline_id: str) -> AutoresearchPipeline:
    """Look up a pipeline by id, before any team scope is known.

    A CLI operator supplies a pipeline id, not a team, so this one read is
    deliberately cross-team. Every caller enters the pipeline's team scope for
    the work that follows.
    """
    try:
        return AutoresearchPipeline.objects.unscoped().select_related("team").get(pk=pipeline_id)
    except AutoresearchPipeline.DoesNotExist:
        raise CommandError(f"Pipeline {pipeline_id} not found.")
