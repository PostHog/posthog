# Test cases for no-new-custom-admin-views.
# ruff: noqa
from django.contrib.admin import action


class TeamAdmin(admin.ModelAdmin):
    # ok: no-new-custom-admin-views
    list_display = ("id", "name")

    # ruleid: no-new-custom-admin-views
    change_form_template = "admin/posthog/team/change_form.html"

    # ruleid: no-new-custom-admin-views
    def get_urls(self):
        # ruleid: no-new-custom-admin-views
        return [path("<path:object_id>/rebuild/", self.admin_site.admin_view(self.rebuild))] + super().get_urls()

    # ok: no-new-custom-admin-views
    def has_delete_permission(self, request, obj=None):
        return False


urlpatterns = [
    # ruleid: no-new-custom-admin-views, no-new-admin-url-routes
    path("admin/tophog/", admin.site.admin_view(tophog_dashboard_view)),
    # ruleid: no-new-admin-url-routes
    path("admin/redisvalues", redis_values_view, name="redis_values"),
    # ruleid: no-new-admin-url-routes
    re_path(r"^admin/apikeysearch/$", api_key_search_view),
    # ok: no-new-admin-url-routes
    path("admin/tophog/", MovedToConsole.page_redirect("TopHog", "/admin/console/tools/tophog/"), name="tophog"),
    # ok: no-new-admin-url-routes
    path("admin", RedirectView.as_view(url="/admin/", permanent=False)),
    # ok: no-new-admin-url-routes
    path("admin/old/", RedirectView.as_view(url="/admin/new/", permanent=False)),
    # ok: no-new-admin-url-routes
    path("admin/", include("loginas.urls")),
    # ok: no-new-admin-url-routes
    path("admin/", admin.site.urls),
    # ok: no-new-admin-url-routes
    path("api/admin/stats/", stats_view),
    # ok: no-new-admin-url-routes
    path("admin/oauth2/callback", admin_oauth2_callback, name="admin_oauth2_callback"),
    # ok: no-new-admin-url-routes
    path("admin/login/user/<str:user_id>/", loginas_user, name="loginas-user-login"),
    # ruleid: no-new-admin-url-routes
    path("admin/logins-report/", logins_report_view),
]


class OrganizationAdmin(admin.ModelAdmin):
    # ruleid: no-new-custom-admin-views
    def get_urls(self):
        return [
            # A URL without admin_view still counts, because it skips Django admin's staff check.
            # ruleid: no-new-custom-admin-views
            path("<path:object_id>/report/", self.report),
            # ruleid: no-new-custom-admin-views
            re_path(r"^(?P<object_id>.+)/usage/$", self.usage),
        ] + super().get_urls()


class CampaignInline(admin.TabularInline):
    # ruleid: no-new-custom-admin-views
    template = "admin/growth/edit_inline/campaign_tabular.html"

    # ruleid: no-new-custom-admin-views
    class Media:
        js = ("admin/js/campaigns.js",)

    def preview(self, obj):
        # ok: no-new-custom-admin-views
        template = "Next up: {}"
        return template.format(obj)


api_urlpatterns = [
    # ok: no-new-custom-admin-views
    path("api/projects/", projects_view),
]


class DeletionRequestAdmin(admin.ModelAdmin):
    # ok: no-new-admin-workflow-hooks
    readonly_fields = ("status",)

    # ok: no-new-admin-workflow-hooks
    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields

    # ruleid: no-new-admin-workflow-hooks
    def save_model(self, request, obj, form, change):
        obj.status = "draft"
        super().save_model(request, obj, form, change)

    # ruleid: no-new-admin-workflow-hooks
    def save_form(self, request, form, change):
        return form.save(commit=False)

    # ruleid: no-new-admin-workflow-hooks
    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(request, object_id, form_url, extra_context)

    # ruleid: no-new-admin-workflow-hooks
    def response_change(self, request, obj):
        return super().response_change(request, obj)


# ok: no-new-admin-workflow-hooks
def save_model(request, obj):
    return obj


class CampaignAdmin(admin.ModelAdmin):
    # ok: no-new-admin-workflow-actions
    @admin.action(description="Mark selected campaigns inactive")
    def mark_inactive(self, request, queryset):
        for campaign in queryset:
            campaign.active = False
            campaign.save(update_fields=["active"])
            self.log_change(request, campaign, "Marked inactive")

    @admin.action(description="Re-sync selected campaigns")
    def resync(self, request, queryset):
        for campaign in queryset:
            # ruleid: no-new-admin-workflow-actions
            resync_campaign.delay(campaign.pk)

    @admin.action
    def export(self, request, queryset):
        # ruleid: no-new-admin-workflow-actions
        return HttpResponse(build_csv(queryset), content_type="text/csv")

    @action(description="Clone selected campaign")
    def clone(self, request, queryset):
        clone = queryset.first().clone()
        # ruleid: no-new-admin-workflow-actions
        return HttpResponseRedirect(reverse("admin:growth_campaign_change", args=[clone.pk]))

    @admin.action(description="Revoke all sessions")
    def revoke_sessions(self, request, queryset):
        if request.POST.get("confirm"):
            return None
        # ruleid: no-new-admin-workflow-actions
        return TemplateResponse(request, "admin/confirm.html", {})

    @admin.action(description="Backfill selected campaigns")
    def backfill(self, request, queryset):
        # ruleid: no-new-admin-workflow-actions
        async_to_sync(client.start_workflow)("backfill", id="backfill", task_queue="general")

    @admin.action(description="Revoke all sessions")
    def revoke_in_console(self, request, queryset):
        query = urlencode([("application", str(pk)) for pk in queryset.values_list("id", flat=True)])
        # ok: no-new-admin-workflow-actions
        return HttpResponseRedirect(f"{reverse('admin_console_tool_operation', args=['oauth-sessions', 'revoke'])}?{query}")

    @admin.action(description="Rebuild in the console")
    def rebuild_in_console(self, request, queryset):
        # ok: no-new-admin-workflow-actions
        return redirect(reverse("admin_console_tool", args=["rebuild"]))

    @admin.action(description="Rebuild by view name")
    def rebuild_by_name(self, request, queryset):
        # ok: no-new-admin-workflow-actions
        return redirect("admin_console_tool", tool_key="rebuild")

    @admin.action(description="Report in the background")
    def report_in_background(self, request, queryset):
        # ruleid: no-new-admin-workflow-actions
        report_task.delay(reverse("admin_console_home"))

    def send_report(self, request, queryset):
        # ok: no-new-admin-workflow-actions
        send_report_task.delay()
        # ok: no-new-admin-workflow-actions
        return redirect("admin:index")
