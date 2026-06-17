import json
from dataclasses import dataclass
from datetime import UTC, datetime

from django.contrib import admin, messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from posthog.models import Project, Team
from posthog.models.group_type_mapping import GroupTypeMapping, invalidate_group_types_cache
from posthog.personhog_client.client import get_personhog_client
from posthog.personhog_client.proto import (
    GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest,
    UpdateGroupTypeMappingRequest,
)


@dataclass
class GroupTypeMappingView:
    """Presentation wrapper around a proto GroupTypeMapping for template rendering."""

    id: int
    team_id: int
    project_id: int
    group_type: str
    group_type_index: int
    name_singular: str | None
    name_plural: str | None
    default_columns: list[str] | None
    detail_dashboard_id: int | None
    created_at: datetime | None
    dashboard_link: str = ""


def _proto_to_view(proto_mapping) -> GroupTypeMappingView:
    default_columns: list[str] | None = None
    if proto_mapping.default_columns:
        default_columns = json.loads(proto_mapping.default_columns)

    created_at: datetime | None = None
    if proto_mapping.created_at:
        created_at = datetime.fromtimestamp(proto_mapping.created_at / 1000, tz=UTC)

    dashboard_id = proto_mapping.detail_dashboard_id or None
    dashboard_link = ""
    if dashboard_id:
        try:
            url = reverse("admin:dashboards_dashboard_change", args=[dashboard_id])
            dashboard_link = format_html('<a href="{}">Dashboard {}</a>', url, dashboard_id)
        except NoReverseMatch:
            dashboard_link = f"Dashboard {dashboard_id}"

    return GroupTypeMappingView(
        id=proto_mapping.id,
        team_id=proto_mapping.team_id,
        project_id=proto_mapping.project_id,
        group_type=proto_mapping.group_type,
        group_type_index=proto_mapping.group_type_index,
        name_singular=proto_mapping.name_singular or None,
        name_plural=proto_mapping.name_plural or None,
        default_columns=default_columns,
        detail_dashboard_id=dashboard_id,
        created_at=created_at,
        dashboard_link=mark_safe(dashboard_link) if dashboard_link else "",  # noqa: S308
    )


def _get_mappings_for_team(team_id: int) -> list[GroupTypeMappingView]:
    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client is not available")
    resp = client.get_group_type_mappings_by_team_id(GetGroupTypeMappingsByTeamIdRequest(team_id=team_id))
    return sorted(
        [_proto_to_view(m) for m in resp.mappings],
        key=lambda m: m.group_type_index,
    )


MAX_SEARCH_RESULTS = 100


@admin.register(GroupTypeMapping)
class GroupTypeMappingAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = [
            path(
                "",
                self.admin_site.admin_view(self.search_view),
                name="grouptypemapping_search",
            ),
            path(
                "team/<int:team_id>/",
                self.admin_site.admin_view(self.team_detail_view),
                name="grouptypemapping_team_detail",
            ),
            path(
                "team/<int:team_id>/edit/<int:group_type_index>/",
                self.admin_site.admin_view(self.edit_view),
                name="grouptypemapping_edit",
            ),
        ]
        return urls

    def search_view(self, request):
        query = request.GET.get("q", "").strip()
        teams: list = []
        teams_truncated = False

        if query:
            qs = Team.objects.select_related("organization")

            if query.isdigit():
                qs = qs.filter(id=int(query))
            else:
                qs = qs.filter(Q(name__icontains=query) | Q(organization__name__icontains=query))

            teams = list(qs[: MAX_SEARCH_RESULTS + 1])
            if len(teams) > MAX_SEARCH_RESULTS:
                teams = teams[:MAX_SEARCH_RESULTS]
                teams_truncated = True

            if teams:
                client = get_personhog_client()
                if client is not None:
                    team_ids = [t.id for t in teams]
                    resp = client.get_group_type_mappings_by_team_ids(
                        GetGroupTypeMappingsByTeamIdsRequest(team_ids=team_ids)
                    )
                    count_by_team: dict[int, int] = {}
                    for result in resp.results:
                        count_by_team[result.key] = len(result.mappings)
                    for team in teams:
                        team.gtm_count = count_by_team.get(team.id, 0)
                else:
                    for team in teams:
                        team.gtm_count = "?"

        return render(
            request,
            "admin/group_type_mapping/search.html",
            {
                "query": query,
                "teams": teams,
                "teams_truncated": teams_truncated,
                "title": "Group type mappings",
                "opts": self.model._meta,
            },
        )

    def team_detail_view(self, request, team_id: int):
        team = Team.objects.select_related("organization").filter(pk=team_id).first()
        if team is None:
            messages.error(request, f"Team {team_id} not found.")
            return redirect(reverse("admin:grouptypemapping_search"))

        project = Project.objects.filter(pk=team.project_id).only("id", "name").first() if team.project_id else None

        try:
            mappings = _get_mappings_for_team(team_id)
        except Exception as e:
            messages.error(request, f"Error fetching group type mappings: {e}")
            mappings = []

        return render(
            request,
            "admin/group_type_mapping/team_detail.html",
            {
                "team": team,
                "project": project,
                "mappings": mappings,
                "title": f"Group type mappings — {team.name}",
                "opts": self.model._meta,
            },
        )

    def edit_view(self, request, team_id: int, group_type_index: int):
        team = Team.objects.select_related("organization").filter(pk=team_id).first()
        if team is None:
            messages.error(request, f"Team {team_id} not found.")
            return redirect(reverse("admin:grouptypemapping_search"))

        project = Project.objects.filter(pk=team.project_id).only("id", "name").first() if team.project_id else None

        try:
            team_mappings = _get_mappings_for_team(team_id)
        except Exception as e:
            messages.error(request, f"Error fetching group type mappings: {e}")
            return redirect(reverse("admin:grouptypemapping_team_detail", args=[team_id]))

        mapping = next((m for m in team_mappings if m.group_type_index == group_type_index), None)
        if mapping is None:
            messages.error(request, f"Group type mapping with index {group_type_index} not found for team {team_id}.")
            return redirect(reverse("admin:grouptypemapping_team_detail", args=[team_id]))

        if request.method == "POST":
            return self._handle_save(request, team, mapping)

        default_columns_json = json.dumps(mapping.default_columns) if mapping.default_columns else ""

        return render(
            request,
            "admin/group_type_mapping/edit.html",
            {
                "team": team,
                "project": project,
                "mapping": mapping,
                "default_columns_json": default_columns_json,
                "title": f"Edit group type mapping: {mapping.group_type}",
                "opts": self.model._meta,
            },
        )

    def _handle_save(self, request, team: Team, mapping: GroupTypeMappingView):
        name_singular = request.POST.get("name_singular", "").strip() or None
        name_plural = request.POST.get("name_plural", "").strip() or None
        default_columns_raw = request.POST.get("default_columns", "").strip()

        default_columns_bytes = b""
        if default_columns_raw:
            try:
                parsed = json.loads(default_columns_raw)
                if not isinstance(parsed, list):
                    messages.error(request, "Default columns must be a JSON array.")
                    return redirect(reverse("admin:grouptypemapping_edit", args=[team.id, mapping.group_type_index]))
                default_columns_bytes = json.dumps(parsed).encode()
            except json.JSONDecodeError:
                messages.error(request, "Invalid JSON for default columns.")
                return redirect(reverse("admin:grouptypemapping_edit", args=[team.id, mapping.group_type_index]))

        client = get_personhog_client()
        if client is None:
            messages.error(request, "personhog client is not available — cannot save.")
            return redirect(reverse("admin:grouptypemapping_edit", args=[team.id, mapping.group_type_index]))

        update_mask = ["name_singular", "name_plural", "default_columns"]
        try:
            client.update_group_type_mapping(
                UpdateGroupTypeMappingRequest(
                    project_id=mapping.project_id,
                    group_type_index=mapping.group_type_index,
                    update_mask=update_mask,
                    name_singular=name_singular or "",
                    name_plural=name_plural or "",
                    default_columns=default_columns_bytes,
                )
            )
        except Exception as e:
            messages.error(request, f"Error saving group type mapping: {e}")
            return redirect(reverse("admin:grouptypemapping_edit", args=[team.id, mapping.group_type_index]))

        if mapping.project_id:
            invalidate_group_types_cache(mapping.project_id)

        messages.success(request, f"Group type mapping '{mapping.group_type}' updated successfully.")
        return redirect(reverse("admin:grouptypemapping_team_detail", args=[team.id]))
