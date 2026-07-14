"""Resolves which warehouse columns to stage for a schema's person-property sources.

Registered as the data-import pipeline's projection hook (see apps.ready). Called from the
pipeline, outside request context, so it scopes explicitly with ``for_team``.
"""

from uuid import UUID

from products.customer_analytics.backend.models import CustomPropertySource, TargetType


def person_property_projection_columns(team_id: int, schema_id: str | UUID) -> list[str] | None:
    """The union of key + mapped columns across the schema's enabled person-target sources, or
    None when the schema feeds no person properties (so the pipeline stages nothing)."""
    sources = CustomPropertySource.objects.for_team(team_id).filter(
        external_data_schema_id=schema_id,
        is_enabled=True,
        definition__target_type=TargetType.PERSON.value,
    )
    columns: set[str] = set()
    for source in sources:
        if source.key_column:
            columns.add(source.key_column)
        columns.update((source.column_property_map or {}).keys())
    return sorted(columns) or None
