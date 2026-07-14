"""Resolves which warehouse columns to stage for a schema's person-property sources.

Registered as the data-import pipeline's projection hook (see apps.ready). Called from the
pipeline, outside request context, so it scopes explicitly with ``for_team``.
"""

from uuid import UUID

from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.warehouse_sources.backend.facade.hooks import PersonPropertySourceProjection


def person_property_projection(team_id: int, schema_id: str | UUID) -> list[PersonPropertySourceProjection] | None:
    """One projection per enabled person-target source on the schema (its key column plus its
    mapped columns), or None when the schema feeds no person properties (so the pipeline stages
    nothing). Sources without a key column are skipped: their rows have no person identifier to
    attach the properties to."""
    sources = CustomPropertySource.objects.for_team(team_id).filter(
        external_data_schema_id=schema_id,
        is_enabled=True,
        definition__target_type=TargetType.PERSON.value,
    )
    projections = [
        PersonPropertySourceProjection(
            key_column=source.key_column,
            columns=frozenset({source.key_column, *(source.column_property_map or {}).keys()}),
        )
        for source in sources
        if source.key_column
    ]
    return projections or None
