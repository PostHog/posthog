# Test cases for no-new-custom-admin-views.
# ruff: noqa


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
    # ruleid: no-new-custom-admin-views
    path("admin/tophog/", admin.site.admin_view(tophog_dashboard_view)),
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


api_urlpatterns = [
    # ok: no-new-custom-admin-views
    path("api/projects/", projects_view),
]
