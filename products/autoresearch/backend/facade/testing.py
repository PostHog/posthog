"""Test-support facade for autoresearch.

Suites outside this product plant pipeline rows through here instead of importing the
model. The model is team-scoped and fail-closed, so this opens the scope the insert needs.
"""

from uuid import UUID

from posthog.models.scoping import team_scope

from products.autoresearch.backend.models import AutoresearchPipeline


def create_pipeline(*, team_id: int, name: str, target_event: str = "$pageview") -> UUID:
    with team_scope(team_id):
        pipeline = AutoresearchPipeline.objects.create(team_id=team_id, name=name, target_event=target_event)
    return pipeline.pk
