from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.product_tours.backend.models import ProductTour


class ProductTourAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "archived",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization", "created_by")
    list_filter = ("archived",)
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    readonly_fields = ("id", "internal_targeting_flag", "created_at", "updated_at")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return ProductTour.all_objects.all()

    def get_exclude(self, request, obj=None):
        exclude = list(super().get_exclude(request, obj) or [])
        if obj:
            exclude.extend(["linked_surveys"])
        return exclude

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for field in ["start_date", "end_date"]:
            if field in form.base_fields:
                form.base_fields[field].required = False
        return form

    @admin.display(description="Team")
    def team_link(self, tour: ProductTour):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[tour.team.pk]),
            tour.team.name,
        )
