"""Resolves the person-property source configs the warehouse import pipeline asks for.

Registered as the data-import pipeline's projection and sync-config hooks (see apps.ready).
Called from the pipeline, outside request context, so it scopes explicitly with ``for_team``.
"""

from uuid import UUID

from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.warehouse_sources.backend.facade.hooks import PersonPropertySourceProjection, PersonPropertySyncSource


def _enabled_person_sources(team_id: int, schema_id: str | UUID) -> list[CustomPropertySource]:
    # Sources without a key column are skipped: their rows have no person identifier to attach
    # the properties to.
    return [
        source
        for source in CustomPropertySource.objects.for_team(team_id).filter(
            external_data_schema_id=schema_id,
            is_enabled=True,
            definition__target_type=TargetType.PERSON.value,
        )
        if source.key_column
    ]


def person_property_projection(team_id: int, schema_id: str | UUID) -> list[PersonPropertySourceProjection] | None:
    """One projection per enabled person-target source on the schema (its key column plus its
    mapped columns), or None when the schema feeds no person properties (so the pipeline stages
    nothing)."""
    projections = [
        PersonPropertySourceProjection(
            key_column=source.key_column,
            columns=frozenset({source.key_column, *(source.column_property_map or {}).keys()}),
        )
        for source in _enabled_person_sources(team_id, schema_id)
    ]
    return projections or None


def person_property_sync_sources(team_id: int, schema_id: str | UUID) -> list[PersonPropertySyncSource] | None:
    """Full sync config per enabled person-target source on the schema, for the warehouse-owned
    post-sync upsert job — or None when the schema feeds no person properties."""
    configs = [
        PersonPropertySyncSource(
            source_id=str(source.id),
            definition_id=str(source.definition_id),
            key_column=source.key_column,
            column_property_map=dict(source.column_property_map or {}),
        )
        for source in _enabled_person_sources(team_id, schema_id)
    ]
    return configs or None
