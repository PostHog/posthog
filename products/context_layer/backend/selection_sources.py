import json
from dataclasses import replace
from urllib.parse import quote
from uuid import UUID

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import CharField, Exists, Model, OuterRef, QuerySet
from django.db.models.functions import Cast

from posthog.hogql.database.database import system_table_denials
from posthog.hogql.database.schema.information_schema import references_denied_table

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import WAREHOUSE_ACCESS_SCOPES, UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.business_knowledge.backend.logic import (
    KnowledgeSearchResult,
    get_chunks_by_ids,
    search_knowledge_for_team,
)
from products.context_layer.backend.selection_search import tokens
from products.context_layer.backend.selection_types import SOURCE_LIMITS, Candidate, SourceKind, digest
from products.data_catalog.backend.facade import api as catalog
from products.skills.backend.models.skills import LLMSkill

MAX_SOURCE_TEXT = 2_800


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
        reference = f"/api/projects/{row.team_id}/data_catalog/metrics/{quote(row.name, safe='')}/"
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


def search_sources(team: Team, user: User, prompt: str, scopes: set[str]) -> list[Candidate]:
    terms = list(dict.fromkeys(tokens(prompt)))[:60]
    if not terms:
        return []
    query = SearchQuery(" | ".join(terms), config="english", search_type="raw")
    candidates: list[Candidate] = []
    if "llm_skill:read" in scopes:
        skills = LLMSkill.objects.filter(team=team, deleted=False, is_latest=True, category="").only(
            "id", "team_id", "name", "description", "version"
        )
        private_controls = AccessControl.objects.filter(
            team=team, resource="llm_skill", resource_id=Cast(OuterRef("id"), CharField())
        )
        skills = skills.filter(~Exists(private_controls))
        candidates.extend(search_rows("skill", skills, query, ("name", "description", "body")))
    if "data_catalog:read" in scopes:
        candidates.extend(
            search_rows("metric", catalog.metrics_for_team(team), query, ("name", "description", "definition"))
        )
        candidates.extend(
            search_rows(
                "certification",
                catalog.certifications_for_team(team).select_related("table", "saved_query"),
                query,
                ("table__name", "saved_query__name", "notes"),
            )
        )
        candidates.extend(
            search_rows(
                "relationship",
                catalog.relationships_for_team(team),
                query,
                ("source_table_name", "joining_table_name", "reasoning"),
            )
        )
    return validate_candidates(team, user, candidates)


def search_rows[T: Model](
    kind: SourceKind, rows: QuerySet[T], query: SearchQuery, fields: tuple[str, ...]
) -> list[Candidate]:
    vector = SearchVector(*fields, config="english")
    matches = (
        rows.annotate(selection_rank=SearchRank(vector, query))
        .filter(selection_rank__gt=0)
        .order_by("-selection_rank", "id")[: SOURCE_LIMITS[kind]]
    )
    return [make_record(kind, row) for row in matches]


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
            team=team, resource__in=["data_catalog", *WAREHOUSE_ACCESS_SCOPES, "external_data_source", "insight"]
        ).exists()
    )
    if shared_catalog and access.check_access_level_for_resource("data_catalog", "viewer"):
        denied = {f"system.{name}" for name in system_table_denials(team, user, access)}
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
    knowledge_team = team.parent_team or team
    shared_knowledge = (
        bool(knowledge_ids)
        and not AccessControl.objects.filter(team=knowledge_team, resource="business_knowledge").exists()
    )
    if (
        knowledge_ids
        and shared_knowledge
        and UserAccessControl(user=user, team=knowledge_team).check_access_level_for_resource(
            "business_knowledge", "viewer"
        )
    ):
        result.extend(
            knowledge_record(item, knowledge_team.id) for item in get_chunks_by_ids(knowledge_team.id, knowledge_ids)
        )
    return result


def search_business_knowledge(team: Team, user: User, query: str) -> list[Candidate]:
    team = team.parent_team or team
    if not posthog_feature_flag_enabled(
        "product-business-knowledge", str(user.distinct_id), team_id=team.id, organization_id=team.organization_id
    ):
        return []
    if not UserAccessControl(user=user, team=team).check_access_level_for_resource("business_knowledge", "viewer"):
        return []
    if AccessControl.objects.filter(team=team, resource="business_knowledge").exists():
        return []
    with team_scope(team.id, canonical=True):
        results = search_knowledge_for_team(
            team, query, limit=SOURCE_LIMITS["business_knowledge"], expand_neighbors=False
        )
    return [knowledge_record(item, team.id) for item in results]


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
