from typing import cast

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from posthog.admin.paginators.no_count_paginator import NoCountPaginator
from posthog.models.organization import Organization, OrganizationAITerms
from posthog.models.user import User


def _desktop_beta_terms_accepted(organization: OrganizationAITerms) -> bool:
    # Deferred: the tasks facade pulls in a heavy dependency tree kept off the web startup path.
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

    return tasks_facade.get_desktop_beta_terms_acceptance(organization.id).is_desktop_beta_terms_accepted


class OrganizationAITermsForm(forms.ModelForm):
    revoke_desktop_beta_terms = forms.BooleanField(
        required=False,
        label="Revoke PostHog Desktop beta terms",
        help_text="An org admin can accept the terms again in organization settings.",
    )

    class Meta:
        model = OrganizationAITerms
        fields = ["is_ai_data_processing_approved"]
        labels = {"is_ai_data_processing_approved": "In-app AI data processing approved"}


@admin.register(OrganizationAITerms)
class OrganizationAITermsAdmin(admin.ModelAdmin):
    form = OrganizationAITermsForm
    show_full_result_count = False
    paginator = NoCountPaginator
    list_display = ("id", "name", "is_ai_data_processing_approved")
    list_display_links = ("id", "name")
    search_fields = ("id", "name", "=team__id")
    readonly_fields = ("id", "name", "desktop_beta_terms_display")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: OrganizationAITerms | None = None) -> bool:
        return False

    def get_fields(self, request: HttpRequest, obj: OrganizationAITerms | None = None) -> tuple[str, ...]:
        fields = ("id", "name", "is_ai_data_processing_approved", "desktop_beta_terms_display")
        if obj is not None and _desktop_beta_terms_accepted(obj):
            return (*fields, "revoke_desktop_beta_terms")
        return fields

    @admin.display(description="PostHog Desktop beta terms")
    def desktop_beta_terms_display(self, organization: OrganizationAITerms) -> str:
        return "Accepted" if _desktop_beta_terms_accepted(organization) else "Not accepted"

    def save_model(
        self, request: HttpRequest, obj: OrganizationAITerms, form: OrganizationAITermsForm, change: bool
    ) -> None:
        if "is_ai_data_processing_approved" in form.changed_data:
            # Save through the concrete model, because the activity log and the Organization signals
            # listen for sender=Organization and ignore a save that this proxy model sends.
            organization = Organization.objects.get(pk=obj.pk)
            organization.is_ai_data_processing_approved = obj.is_ai_data_processing_approved
            organization.save(update_fields=["is_ai_data_processing_approved"])
        if form.cleaned_data.get("revoke_desktop_beta_terms"):
            from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

            tasks_facade.revoke_desktop_beta_terms(obj.id, cast(User, request.user))
