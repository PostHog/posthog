"""The dashboard templates a project sees, saves, changes and copies through the template API."""

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError
from django.db.models import Q, QuerySet
from django.db.models.expressions import OrderBy
from django.db.models.functions import Lower

import structlog
from rest_framework import serializers

from posthog.exceptions_capture import capture_exception
from posthog.helpers.full_text_search import build_rank
from posthog.models.team.team import Team
from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.dashboards.backend.facade import contracts
from products.dashboards.backend.facade.enums import DashboardTemplateOrdering, DashboardTemplateScope
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

logger = structlog.get_logger(__name__)


def organization_dashboard_template_limit_detail() -> str:
    return (
        f"Your organization has reached the limit of {contracts.MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION} "
        "dashboard templates. Delete a template before creating or restoring another."
    )


def _enforce_organization_limit(organization_id: UUID) -> None:
    # Counts the live templates of the organization's projects. A global template has no project, so it does not count.
    if (
        DashboardTemplate.objects.filter(team__organization_id=organization_id).count()
        >= contracts.MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION
    ):
        raise contracts.DashboardTemplateWriteRejected(organization_dashboard_template_limit_detail())


def _list_order(ordering: DashboardTemplateOrdering | None) -> list[Any]:
    # Neither template_name nor created_at is unique across the visible templates, so each order needs `id`
    # to page reliably. The `id` direction mirrors the column above it.
    match ordering:
        case DashboardTemplateOrdering.NAME_DESCENDING:
            return ["-is_featured", OrderBy(Lower("template_name"), descending=True), "-id"]
        case DashboardTemplateOrdering.CREATED_AT:
            return ["-is_featured", "created_at", "id"]
        case DashboardTemplateOrdering.CREATED_AT_DESCENDING:
            return ["-is_featured", "-created_at", "-id"]
        case _:
            return ["-is_featured", Lower("template_name"), "id"]


def _visible_templates(
    *, team_id: int, organization_id: UUID, filters: contracts.DashboardTemplateFilters, include_deleted: bool
) -> QuerySet[DashboardTemplate]:
    # Organization-scoped templates are visible to every team in the same organization. The org arm must
    # always be AND-ed with `team__organization_id` so it never leaks templates from other organizations.
    organization_templates = Q(scope=DashboardTemplateScope.ORGANIZATION) & Q(team__organization_id=organization_id)
    match filters.scope:
        case DashboardTemplateScope.FEATURE_FLAG:
            # Feature-flag templates are implicitly global, so they're not associated with any teams.
            condition = Q(scope=DashboardTemplateScope.FEATURE_FLAG)
        case DashboardTemplateScope.GLOBAL:
            condition = Q(scope=DashboardTemplateScope.GLOBAL)
        case DashboardTemplateScope.ONLY_TEAM:
            condition = Q(team_id=team_id) & Q(scope=DashboardTemplateScope.ONLY_TEAM)
        case DashboardTemplateScope.ORGANIZATION:
            condition = organization_templates
        case _:
            # The new dashboard picker shows global, organization, and this team's templates.
            condition = Q(team_id=team_id) | Q(scope=DashboardTemplateScope.GLOBAL) | organization_templates

    templates = DashboardTemplate.objects_including_soft_deleted.filter(condition).select_related("created_by")

    if filters.is_featured is not None:
        templates = templates.filter(is_featured=filters.is_featured)
        # Feature-flag templates are tied to team_id but belong in `?scope=feature_flag` lists only;
        # featured carousels use `?is_featured=true` without that scope and must not surface them.
        if filters.is_featured and filters.scope != DashboardTemplateScope.FEATURE_FLAG:
            templates = templates.exclude(scope=DashboardTemplateScope.FEATURE_FLAG)

    if filters.search is not None:
        templates = templates.annotate(
            rank=build_rank({"template_name": "A", "dashboard_description": "C", "tags": "B"}, filters.search),
        )
        templates = templates.filter(rank__gt=0.05).order_by("-is_featured", "-rank", Lower("template_name"), "id")
    else:
        templates = templates.order_by(*_list_order(filters.ordering))

    # Only a write resolves a soft-deleted template, so that the owning project can undo a delete with
    # PATCH `{deleted: false}`. Reads leave them out, so a sibling project that captured the UUID can't GET
    # an organization template after its owning project deleted it.
    if not include_deleted:
        templates = templates.exclude(deleted=True)
    return templates


def list_templates(
    *, team_id: int, organization_id: UUID, filters: contracts.DashboardTemplateFilters, page: PageRequest
) -> Page[DashboardTemplate]:
    templates = _visible_templates(
        team_id=team_id, organization_id=organization_id, filters=filters, include_deleted=False
    )
    return select_page(strict_fetch(templates), page)


def get_template(
    *,
    team_id: int,
    organization_id: UUID,
    template_id: UUID,
    filters: contracts.DashboardTemplateFilters,
    include_deleted: bool,
) -> DashboardTemplate | None:
    templates = _visible_templates(
        team_id=team_id, organization_id=organization_id, filters=filters, include_deleted=include_deleted
    )
    return templates.filter(pk=template_id).first()


def _check_template_groups(write: contracts.DashboardTemplateWrite) -> None:
    # Imported at call time: the customization module loads the widget registry, which imports the dashboards facade.
    from products.dashboards.backend.customization import validate_template_groups  # noqa: PLC0415

    try:
        validate_template_groups(write.customization, write.tiles)
    except serializers.ValidationError as error:
        # validate_template_groups rejects one field, `customization` or `tiles`, with one message.
        ((field, messages),) = cast(dict[str, Any], error.detail).items()
        message = messages[0] if isinstance(messages, list) else messages
        raise contracts.DashboardTemplateWriteRejected(str(message), field=field) from error


def _check_organization_template_name(
    write: contracts.DashboardTemplateWrite, *, team_id: int, template: DashboardTemplate | None
) -> None:
    """Organization-scoped templates must have a unique name within their organization."""
    effective_scope = write.scope or (template.scope if template is not None else None)
    if effective_scope != DashboardTemplateScope.ORGANIZATION:
        return
    template_name = write.template_name
    if template_name is None and template is not None:
        template_name = template.template_name
    if not template_name:
        return
    organization_id = Team.objects.filter(pk=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return
    clashing = DashboardTemplate.objects.filter(
        scope=DashboardTemplateScope.ORGANIZATION,
        team__organization_id=organization_id,
        template_name=template_name,
    )
    if template is not None:
        clashing = clashing.exclude(pk=template.pk)
    if clashing.exists():
        raise contracts.DashboardTemplateWriteRejected(
            "An organization template with this name already exists in this organization.",
            field="template_name",
            code="unique_org_template_name",
        )


def _tiles_without_agent_context(tiles: Any) -> Any:
    if not isinstance(tiles, list):
        return tiles
    return [
        {key: value for key, value in tile.items() if key != "agent_context"} if isinstance(tile, dict) else tile
        for tile in tiles
    ]


@contextmanager
def _duplicate_name_rejected() -> Iterator[None]:
    try:
        yield
    except IntegrityError as error:
        if "unique_template_name_per_team" not in str(error):
            raise
        raise contracts.DashboardTemplateWriteRejected(
            "A dashboard template with this name already exists for this project.",
            code="unique_template_name_per_team",
        ) from error


def _written_fields(write: contracts.DashboardTemplateWrite) -> dict[str, Any]:
    return {name: getattr(write, name) for name in write.fields_set}


def create_template(
    *, team_id: int, organization_id: UUID, created_by_id: int | None, write: contracts.DashboardTemplateWrite
) -> DashboardTemplate:
    _check_template_groups(write)
    _check_organization_template_name(write, team_id=team_id, template=None)

    fields = _written_fields(write)
    if not fields.get("tiles"):
        raise contracts.DashboardTemplateWriteRejected("You need to provide tiles for the template.")
    fields["scope"] = fields.get("scope") or DashboardTemplateScope.ONLY_TEAM
    if fields["scope"] != DashboardTemplateScope.ONLY_TEAM:
        fields["tiles"] = _tiles_without_agent_context(fields["tiles"])

    _enforce_organization_limit(organization_id)
    with _duplicate_name_rejected():
        return DashboardTemplate.objects.create(team_id=team_id, created_by_id=created_by_id, **fields)


def update_template(
    *,
    team_id: int,
    organization_id: UUID,
    template_id: UUID,
    filters: contracts.DashboardTemplateFilters,
    write: contracts.DashboardTemplateWrite,
) -> DashboardTemplate:
    template = get_template(
        team_id=team_id, organization_id=organization_id, template_id=template_id, filters=filters, include_deleted=True
    )
    if template is None:
        raise contracts.DashboardTemplateNotFound(str(template_id))

    _check_template_groups(write)
    _check_organization_template_name(
        write, team_id=template.team_id if template.team_id is not None else team_id, template=template
    )

    fields = _written_fields(write)
    if fields.get("deleted") is False and template.deleted and template.team_id is not None:
        restored_organization_id = (
            Team.objects.filter(pk=template.team_id).values_list("organization_id", flat=True).first()
        )
        if restored_organization_id is not None:
            _enforce_organization_limit(restored_organization_id)

    # A global template with no team becomes team-scoped to the project issuing the update. Only staff
    # can reach this: the write permission refuses everyone else an update of a global template.
    if (
        fields.get("scope") == DashboardTemplateScope.ONLY_TEAM
        and template.scope == DashboardTemplateScope.GLOBAL
        and template.team_id is None
    ):
        fields["team_id"] = team_id

    if fields.get("scope", template.scope) != DashboardTemplateScope.ONLY_TEAM:
        fields["tiles"] = _tiles_without_agent_context(fields.get("tiles", template.tiles))

    for name, value in fields.items():
        setattr(template, name, value)
    with _duplicate_name_rejected():
        template.save()
    return template


def copy_source(*, team_id: int, organization_id: UUID, source_template_id: UUID) -> DashboardTemplate:
    """The team template another project of the organization copies into the project `team_id`."""
    # The source belongs to another project, so this reads it by id alone. The checks below hold it to the organization.
    source = DashboardTemplate.objects_including_soft_deleted.filter(id=source_template_id).first()
    if source is None or source.deleted:
        raise contracts.DashboardTemplateNotFound(str(source_template_id))

    if source.scope == DashboardTemplateScope.FEATURE_FLAG:
        raise contracts.DashboardTemplateWriteRejected(
            "Feature-flag templates cannot be copied with this endpoint.", field="source_template_id"
        )
    if source.scope != DashboardTemplateScope.ONLY_TEAM or source.team_id is None:
        raise contracts.DashboardTemplateWriteRejected(
            "Only project-scoped templates can be copied to another project.", field="source_template_id"
        )
    if source.team_id == team_id:
        raise contracts.DashboardTemplateWriteRejected(
            "Source and destination must be different projects.", field="source_template_id"
        )

    source_organization_id = Team.objects.filter(pk=source.team_id).values_list("organization_id", flat=True).first()
    if source_organization_id is None or source_organization_id != organization_id:
        raise contracts.DashboardTemplateNotFound(str(source_template_id))
    return source


def _copy_name_candidates(base_name: str) -> Iterator[str]:
    yield base_name
    yield f"{base_name} (copy)"
    n = 2
    while True:
        yield f"{base_name} (copy {n})"
        n += 1


def _unique_copy_name(*, team_id: int, base_name: str) -> str:
    """Resolves `template_name` collisions on the target team by suffixing `(copy)`, `(copy 2)`, …"""
    max_attempts = 50
    candidates = _copy_name_candidates(base_name)
    for _ in range(max_attempts):
        name = next(candidates)
        if not DashboardTemplate.objects.filter(team_id=team_id, template_name=name).exists():
            return name
    raise contracts.DashboardTemplateWriteRejected(
        "Could not find an available template name after multiple attempts. Rename the source template and try again.",
        code="template_name_exhausted",
    )


def copy_template(
    *, team_id: int, organization_id: UUID, source: contracts.DashboardTemplate, created_by_id: int | None
) -> DashboardTemplate:
    _enforce_organization_limit(organization_id)
    base_name = (source.template_name or "").strip() or "Untitled template"
    return DashboardTemplate.objects.create(
        team_id=team_id,
        template_name=_unique_copy_name(team_id=team_id, base_name=base_name),
        dashboard_description=source.dashboard_description,
        # TODO(analytics-platform): dashboard_filters and variables are copied verbatim; both can embed
        # project-scoped references (e.g. cohort IDs in filter properties; variable defaults for events,
        # actions, or properties) that do not exist or differ on the target project. Tile queries have the
        # same class of issue. Consider validation and/or ID rewriting (cf. resource_transfer visitors).
        dashboard_filters=source.dashboard_filters,
        tiles=source.tiles or [],
        variables=source.variables,
        customization=source.customization,
        tags=source.tags or [],
        scope=DashboardTemplateScope.ONLY_TEAM,
        is_featured=False,
        image_url=None,
        availability_contexts=None,
        deleted=False,
        created_by_id=created_by_id,
    )


def for_display(
    template: contracts.DashboardTemplate, *, ai_data_processing_approved: bool
) -> contracts.DashboardTemplate:
    if template.scope == DashboardTemplateScope.ONLY_TEAM and ai_data_processing_approved:
        return template
    return dataclasses.replace(template, tiles=_tiles_without_agent_context(template.tiles))


def _warehouse_table_names(node: Any) -> set[str]:
    """Recursively collect `DataWarehouseNode.table_name` values from a query JSON tree."""
    names: set[str] = set()
    if isinstance(node, dict):
        if node.get("kind") == "DataWarehouseNode":
            table_name = node.get("table_name")
            if isinstance(table_name, str) and table_name:
                names.add(table_name)
        for value in node.values():
            names |= _warehouse_table_names(value)
    elif isinstance(node, list):
        for item in node:
            names |= _warehouse_table_names(item)
    return names


def non_portable_references(template: contracts.DashboardTemplate) -> contracts.NonPortableReferences:
    """Project-scoped references in template tiles that may not resolve when used in another project.

    Events and properties are portable (matched by name), so they are not reported.
    """
    # Imported at call time: the visitors package loads the dashboard widget visitor, which imports the dashboards facade.
    from posthog.models.resource_transfer.visitors.insight import InsightVisitor  # noqa: PLC0415

    action_ids: set[int] = set()
    cohort_ids: set[int] = set()
    warehouse_tables: set[str] = set()
    tiles = template.tiles if isinstance(template.tiles, list) else []
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        query = tile.get("query")
        if not isinstance(query, dict):
            continue
        try:
            action_ids |= InsightVisitor._extract_action_ids(None, query)
            cohort_ids |= InsightVisitor._extract_cohort_ids(None, query)
        except (ValueError, TypeError) as exc:
            # Detection is best-effort; a malformed tile must never break serialization.
            logger.warning("dashboard_template_non_portable_reference_detection_failed", exc_info=exc)
            capture_exception(exc)
        warehouse_tables |= _warehouse_table_names(query)
    return contracts.NonPortableReferences(
        actions=len(action_ids), cohorts=len(cohort_ids), warehouse_tables=tuple(sorted(warehouse_tables))
    )
