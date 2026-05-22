import threading

from django.contrib import admin
from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

from posthog.models import Project, Team
from posthog.models.group_type_mapping import GroupTypeMapping, invalidate_group_types_cache


@admin.register(GroupTypeMapping)
class GroupTypeMappingAdmin(admin.ModelAdmin):
    list_display = (
        "group_type_index",
        "group_type",
        "name_singular",
        "name_plural",
        "team_link",
        "created_at",
    )
    search_fields = ("group_type", "name_singular", "name_plural")
    fields = (
        "team_link",
        "project_link",
        "group_type",
        "group_type_index",
        "name_singular",
        "name_plural",
        "default_columns",
        "detail_dashboard_link",
        "created_at",
    )
    readonly_fields = (
        "team_link",
        "project_link",
        "group_type",
        "group_type_index",
        "detail_dashboard_link",
    )

    # ModelAdmin is a per-site singleton; under threaded WSGI we can't stash request-scoped
    # state on `self` without one thread's cache leaking into another's row rendering.
    _request_local = threading.local()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.project_id:
            invalidate_group_types_cache(obj.project_id)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # `posthog_grouptypemapping` lives in the persons DB while Team/Project/Dashboard
        # live in the main DB, so Django can't JOIN across them. Prefetch the Team rows
        # for the current page from the main DB to avoid N+1 in team_link's list-view use.
        team_ids = list(qs.values_list("team_id", flat=True).distinct()[:1000])
        self._request_local.team_cache = Team.objects.in_bulk(team_ids) if team_ids else {}
        return qs

    def get_search_results(self, request, queryset, search_term):
        base_queryset = queryset
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        if not search_term:
            return queryset, may_have_duplicates

        # Resolve team/org name matches on the main DB first, then add an IN-filter on
        # the persons-DB queryset – see get_queryset above for the same cross-DB pattern.
        team_ids = list(
            Team.objects.filter(
                Q(name__icontains=search_term) | Q(organization__name__icontains=search_term)
            ).values_list("id", flat=True)[:1000]
        )
        if team_ids:
            queryset = queryset | base_queryset.filter(team_id__in=team_ids)
            may_have_duplicates = True

        return queryset, may_have_duplicates

    @admin.display(description="Team")
    def team_link(self, group_type_mapping: GroupTypeMapping) -> str:
        team_id = group_type_mapping.team_id
        if not team_id:
            return "-"
        team = getattr(self._request_local, "team_cache", {}).get(team_id)
        if team is None:
            team = Team.objects.filter(pk=team_id).only("id", "name").first()
        if team is None:
            return f"Team {team_id} (not found)"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[team.pk]),
            team.name,
        )

    @admin.display(description="Project")
    def project_link(self, group_type_mapping: GroupTypeMapping) -> str:
        project_id = group_type_mapping.project_id
        if not project_id:
            return "-"
        project = Project.objects.filter(pk=project_id).only("id", "name").first()
        if project is None:
            return f"Project {project_id} (not found)"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_project_change", args=[project.pk]),
            project.name,
        )

    @admin.display(description="Detail dashboard")
    def detail_dashboard_link(self, group_type_mapping: GroupTypeMapping) -> str:
        dashboard_id = group_type_mapping.detail_dashboard_id
        if not dashboard_id:
            return "-"
        try:
            url = reverse("admin:dashboards_dashboard_change", args=[dashboard_id])
        except NoReverseMatch:
            return f"Dashboard {dashboard_id}"
        return format_html('<a href="{}">Dashboard {}</a>', url, dashboard_id)
