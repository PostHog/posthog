"""Resolves the person-property source configs the warehouse import pipeline asks for.

Registered as the data-import pipeline's projection and sync-config hooks (see apps.ready).
Called from the pipeline, outside request context, so it scopes explicitly with ``for_team``.

Both resolvers are the feature's pipeline choke point: they return None when the
``warehouse-person-properties`` rollout flag is off for the team's organization, which switches
off staging, the post-sync workflow gate, and the upsert in one place. The flag is only evaluated
once a schema is confirmed to have enabled person sources, so unconfigured schemas (the vast
majority of syncs) never pay a flag-service call.
"""

from uuid import UUID

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.customer_analytics.backend.constants import WAREHOUSE_PERSON_PROPERTIES_FLAG
from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.warehouse_sources.backend.facade.hooks import PersonPropertySourceProjection, PersonPropertySyncSource


def person_properties_flag_enabled(team_id: int) -> bool:
    """Whether the warehouse -> person properties rollout flag is on for the team's organization.

    Fails closed: an unknown team or a flag-service error disables the feature for that call
    rather than letting an unvetted rollout through.
    """
    try:
        organization_id = str(Team.objects.only("organization_id").get(id=team_id).organization_id)
    except Team.DoesNotExist:
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_PERSON_PROPERTIES_FLAG,
                organization_id,
                groups={"organization": organization_id},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


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
    sources = _enabled_person_sources(team_id, schema_id)
    if not sources or not person_properties_flag_enabled(team_id):
        return None
    return [
        PersonPropertySourceProjection(
            key_column=source.key_column,
            columns=frozenset({source.key_column, *(source.column_property_map or {}).keys()}),
        )
        for source in sources
    ]


def person_property_sync_sources(team_id: int, schema_id: str | UUID) -> list[PersonPropertySyncSource] | None:
    """Full sync config per enabled person-target source on the schema, for the warehouse-owned
    post-sync upsert job — or None when the schema feeds no person properties."""
    sources = _enabled_person_sources(team_id, schema_id)
    if not sources or not person_properties_flag_enabled(team_id):
        return None
    return [
        PersonPropertySyncSource(
            source_id=str(source.id),
            definition_id=str(source.definition_id),
            key_column=source.key_column,
            column_property_map=dict(source.column_property_map or {}),
        )
        for source in sources
    ]
