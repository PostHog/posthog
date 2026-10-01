import json
import time
from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.core.cache import cache
from django.db.models import CharField, Exists, OuterRef
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.information_schema import references_denied_table

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.business_knowledge.backend.logic import (
    KnowledgeSearchResult,
    get_chunks_by_ids,
    search_knowledge_for_team,
)
from products.context_layer.backend.models import ContextSelectionProjection
from products.context_layer.backend.selection_types import Candidate, SourceKind, digest
from products.data_catalog.backend.facade import api as catalog
from products.skills.backend.models.skills import LLMSkill

PROJECTION_TTL = 600
REFRESH_AFTER = 120
MAX_RECORDS_PER_KIND = 2_000
MAX_SOURCE_TEXT = 2_800


def projection_key(team_id: int) -> str:
    return f"context_selection:projection:v1:{team_id}"


def make_record(kind: SourceKind, row: object) -> Candidate:
    payload: dict[str, object]
    tables: tuple[str, ...]
    # Source models have different shapes; serialize only the fields used by retrieval.
    if isinstance(row, LLMSkill):
        payload = {"description": row.description}
        title, status, tables = row.name, "skill", ()
        reference = f"skill-get: skill_name={row.name}, version={row.version}"
        revision = str(row.version)
    elif isinstance(row, catalog.Metric):
        payload = {"description": row.description, "definition": row.definition, "unit": row.unit}
        title, status, tables = row.name, row.status, tuple(row.referenced_table_names)
        reference = f"/api/projects/{row.team_id}/data_catalog/metrics/{row.id}/"
        revision = row.updated_at.isoformat() if row.updated_at else digest(payload)
    elif isinstance(row, catalog.TableCertification):
        title = catalog.certification_target_name(row)
        payload = {"notes": row.notes, "proposed_status": row.proposed_status}
        status, tables = row.status, (title,)
        reference = f"/api/projects/{row.team_id}/data_catalog/certifications/{row.id}/"
        revision = row.updated_at.isoformat() if row.updated_at else digest(payload)
    elif isinstance(row, catalog.RelationshipProposal):
        title = f"{row.source_table_name} -> {row.joining_table_name}"
        payload = {"source_key": row.source_table_key, "joining_key": row.joining_table_key, "reasoning": row.reasoning}
        status, tables = row.status, (row.source_table_name, row.joining_table_name)
        reference = f"/api/projects/{row.team_id}/data_catalog/relationship_proposals/{row.id}/"
        revision = row.updated_at.isoformat() if row.updated_at else digest(payload)
    else:
        raise TypeError("unsupported_context_source")
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > MAX_SOURCE_TEXT:
        text = text[:MAX_SOURCE_TEXT] + " [truncated; read the source]"
    return Candidate(
        id=str(row.id),
        kind=kind,
        title=title,
        text=text,
        revision=revision,
        status=status,
        reference=reference,
        tables=tables,
    )


def refresh_projection(team_id: int) -> dict:
    started = time.monotonic()
    team = Team.objects.get(id=team_id)
    groups = {
        "skill": LLMSkill.objects.filter(team=team, deleted=False, is_latest=True, category="").only(
            "id", "name", "description", "version"
        ),
        "metric": catalog.metrics_for_team(team),
        "certification": catalog.certifications_for_team(team).select_related("table", "saved_query"),
        "relationship": catalog.relationships_for_team(team),
    }
    # Only project-shared source metadata belongs in an archive exported for this experiment.
    restrictions = AccessControl.objects.filter(team=team)
    if restrictions.filter(resource="llm_skill", resource_id__isnull=True).exists():
        groups["skill"] = groups["skill"].none()
    else:
        groups["skill"] = (
            groups["skill"]
            .alias(
                restricted=Exists(
                    restrictions.filter(resource="llm_skill", resource_id=Cast(OuterRef("id"), CharField()))
                )
            )
            .filter(restricted=False)
        )
    if restrictions.filter(
        resource__in=["data_catalog", "warehouse_table", "external_data_source", "insight"]
    ).exists():
        for kind in ("metric", "certification", "relationship"):
            groups[kind] = groups[kind].none()
    records: list[dict] = []
    capped = []
    for kind, queryset in groups.items():
        rows = list(queryset.order_by("id")[: MAX_RECORDS_PER_KIND + 1])
        if len(rows) > MAX_RECORDS_PER_KIND:
            capped.append(kind)
        records.extend(make_record(cast(SourceKind, kind), row).as_json() for row in rows[:MAX_RECORDS_PER_KIND])
    projection = {"version": digest(records), "created_at": time.time(), "records": records, "capped_sources": capped}
    projection["refresh_seconds"] = time.monotonic() - started
    archive, created = ContextSelectionProjection.objects.get_or_create(
        team=team,
        version=projection["version"],
        defaults={"payload": projection, "expires_at": timezone.now() + timedelta(days=91)},
    )
    if not created:
        ContextSelectionProjection.objects.filter(id=archive.id).update(expires_at=timezone.now() + timedelta(days=91))
    projection["archive_id"] = str(archive.id)
    cache.set(projection_key(team_id), projection, timeout=PROJECTION_TTL)
    return projection


def load_projection(team_id: int) -> dict | None:
    projection = cache.get(projection_key(team_id))
    if projection is None or time.time() - projection["created_at"] >= REFRESH_AFTER:
        # Import only when dispatching to avoid the Celery task importing itself during discovery.
        from products.context_layer.backend.tasks import refresh_context_selection_projection  # noqa: PLC0415

        key = f"{projection_key(team_id)}:refresh"
        if cache.add(key, True, timeout=60):
            try:
                refresh_context_selection_projection.delay(team_id)
            except Exception:
                cache.delete(key)
                raise
    return projection


def validate_candidates(team: Team, user: User, candidates: list[Candidate]) -> list[Candidate]:
    if not candidates:
        return []
    access = UserAccessControl(user=user, team=team)
    ids = {
        kind: [c.id for c in candidates if c.kind == kind]
        for kind in ("skill", "metric", "certification", "relationship")
    }
    # Object-specific controls can hide a source from other members of a shared conversation.
    private_skill_ids = list(
        AccessControl.objects.filter(team=team, resource="llm_skill", resource_id__in=ids["skill"]).values_list(
            "resource_id", flat=True
        )
    )
    result: list[Candidate] = []
    shared_skills = (
        bool(ids["skill"])
        and not AccessControl.objects.filter(team=team, resource="llm_skill", resource_id__isnull=True).exists()
    )
    if shared_skills and access.check_access_level_for_resource("llm_skill", "viewer"):
        skills = access.filter_queryset_by_access_level(
            LLMSkill.objects.filter(team=team, id__in=ids["skill"], deleted=False, is_latest=True, category="").exclude(
                id__in=private_skill_ids
            ),
            resource="llm_skill",
        )
        result.extend(make_record("skill", row) for row in skills)
    # Shared chats may outlive the actor. Until audience-aware delivery exists, skip
    # semantic sources in projects with customized underlying resource access.
    shared_catalog = (
        any(ids[k] for k in ("metric", "certification", "relationship"))
        and not AccessControl.objects.filter(
            team=team, resource__in=["data_catalog", "warehouse_table", "external_data_source", "insight"]
        ).exists()
    )
    if shared_catalog and access.check_access_level_for_resource("data_catalog", "viewer"):
        denied = Database.create_for(team=team, user=user, user_access_control=access)._denied_tables
        metrics = list(catalog.metrics_for_team(team).filter(id__in=ids["metric"]))
        drift = catalog.compute_drift(metrics)
        result.extend(
            replace(make_record("metric", row), status="drifted" if drift[row.id] else row.status) for row in metrics
        )
        result.extend(
            make_record("certification", row)
            for row in catalog.certifications_for_team(team)
            .filter(id__in=ids["certification"])
            .select_related("table", "saved_query")
        )
        result.extend(
            make_record("relationship", row)
            for row in catalog.relationships_for_team(team).filter(id__in=ids["relationship"])
        )
        result = [c for c in result if not references_denied_table(list(c.tables), denied)]
    knowledge_ids = [UUID(c.id) for c in candidates if c.kind == "business_knowledge"]
    shared_knowledge = (
        bool(knowledge_ids) and not AccessControl.objects.filter(team=team, resource="business_knowledge").exists()
    )
    if knowledge_ids and shared_knowledge and access.check_access_level_for_resource("business_knowledge", "viewer"):
        result.extend(knowledge_record(item, team.id) for item in get_chunks_by_ids(team.id, knowledge_ids))
    return result


def search_business_knowledge(team: Team, user: User, query: str) -> list[Candidate]:
    if not posthog_feature_flag_enabled(
        "product-business-knowledge", str(user.distinct_id), team_id=team.id, organization_id=team.organization_id
    ):
        return []
    if not UserAccessControl(user=user, team=team).check_access_level_for_resource("business_knowledge", "viewer"):
        return []
    if AccessControl.objects.filter(team=team, resource="business_knowledge").exists():
        return []
    results = search_knowledge_for_team(team, query, limit=8)
    return [knowledge_record(item, team.id) for item in results[:8]]


def knowledge_record(item: KnowledgeSearchResult, team_id: int) -> Candidate:
    return Candidate(
        id=str(item.chunk_id),
        kind="business_knowledge",
        title=item.document_title,
        text=item.content[:MAX_SOURCE_TEXT],
        revision=digest(item.content),
        status="generated_source" if item.is_generated else "source_passage",
        reference=f"/api/projects/{team_id}/business_knowledge/documents/{item.document_id}/window/?around_ordinal={item.ordinal}",
        document_id=str(item.document_id),
    )
