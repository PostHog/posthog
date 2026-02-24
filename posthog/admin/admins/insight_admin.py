from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import Insight


class InsightAdminForm(forms.ModelForm):
    sampling_factor = forms.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Sampling factor between 0 and 1 (e.g., 0.1 for 10% sampling). Leave empty to disable sampling.",
    )

    class Meta:
        model = Insight
        exclude = ("layouts",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["sampling_factor"].initial = self._get_sampling_factor()
        if "filters" in self.fields:
            self.fields["filters"].required = False

    def _get_sampling_factor(self):
        if not self.instance.query:
            return None
        source = self.instance.query.get("source", {})
        return source.get("samplingFactor")

    def save(self, commit=True):
        instance = super().save(commit=False)
        sampling_factor = self.cleaned_data.get("sampling_factor")

        if instance.query is None:
            instance.query = {}

        if "source" not in instance.query:
            instance.query["source"] = {}

        if sampling_factor is not None and sampling_factor < 1.0:
            instance.query["source"]["samplingFactor"] = sampling_factor
        elif "samplingFactor" in instance.query.get("source", {}):
            del instance.query["source"]["samplingFactor"]

        if commit:
            instance.save()
        return instance


class InsightAdmin(admin.ModelAdmin):
    form = InsightAdminForm
    exclude = ("layouts",)

    list_display = (
        "id",
        "short_id",
        "effective_name",
        "team_link",
        "organization_link",
        "sampling_factor_display",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "short_id", "effective_name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "short_id", "team__name", "team__organization__name")
    readonly_fields = (
        "deprecated_tags",
        "deprecated_tags_v2",
        "dive_dashboard",
        "sampling_factor_readonly",
        "created_at",
    )
    autocomplete_fields = ("team", "dashboard", "created_by", "last_modified_by")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("name", "description", "team", "short_id")}),
        ("Query", {"fields": ("query", "filters", "filters_hash")}),
        (
            "Sampling (deprecated)",
            {
                "fields": ("sampling_factor", "sampling_factor_readonly"),
                "description": "Sampling is deprecated. Use this section to view or remove sampling from insights.",
            },
        ),
        ("Metadata", {"fields": ("saved", "favorited", "deleted", "is_sample", "order")}),
        ("Timestamps", {"fields": ("created_at", "last_modified_at", "created_by", "last_modified_by")}),
        (
            "Deprecated fields",
            {
                "classes": ("collapse",),
                "fields": ("dashboard", "dive_dashboard", "deprecated_tags", "deprecated_tags_v2"),
            },
        ),
    )

    def effective_name(self, insight: Insight):
        return insight.name or format_html("<i>{}</>", insight.derived_name)

    @admin.display(description="Sampling")
    def sampling_factor_display(self, insight: Insight):
        factor = self._get_sampling_factor(insight)
        if factor is None:
            return "-"
        return f"{factor * 100:.1f}%"

    @admin.display(description="Current sampling factor")
    def sampling_factor_readonly(self, insight: Insight):
        factor = self._get_sampling_factor(insight)
        if factor is None:
            return "No sampling configured"
        return f"{factor * 100:.1f}% ({factor})"

    def _get_sampling_factor(self, insight: Insight):
        if not insight.query:
            return None
        source = insight.query.get("source", {})
        return source.get("samplingFactor")

    @admin.display(description="Team")
    def team_link(self, insight: Insight):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[insight.team.pk]),
            insight.team.name,
        )

    @admin.display(description="Organization")
    def organization_link(self, insight: Insight):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[insight.team.organization.pk]),
            insight.team.organization.name,
        )
