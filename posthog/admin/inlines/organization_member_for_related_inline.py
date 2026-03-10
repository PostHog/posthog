from typing import Any

from django.contrib import admin
from django.forms import BaseInlineFormSet, ModelForm, modelformset_factory
from django.urls import reverse
from django.utils.html import format_html

from django_admin_inline_paginator.admin import PaginationFormSetBase, TabularInlinePaginated

from posthog.models.organization import Organization, OrganizationMembership

_ORGANIZATION_FK = OrganizationMembership._meta.get_field("organization")


class _ReadOnlyForm(ModelForm):
    class Meta:
        model = OrganizationMembership
        fields = ()


class _OrganizationMemberFormSet(PaginationFormSetBase, BaseInlineFormSet):
    """FormSet that filters OrganizationMembership by the parent object's organization.

    Django's BaseInlineFormSet normally filters by a FK pointing at the parent
    model.  Here the parent is Team or Project, but the FK points at
    Organization.  We skip BaseInlineFormSet's __init__
    (via explicit super(BaseInlineFormSet, self) call) to bypass its FK
    wiring and provide our own queryset instead.
    """

    fk: Any = _ORGANIZATION_FK

    def __init__(self, data=None, files=None, instance=None, save_as_new=False, **kwargs):
        self.instance: Any = instance
        # Django's admin template reads formset.save_as_new.
        self.save_as_new = save_as_new
        if instance and hasattr(instance, "organization_id"):
            qs = (
                OrganizationMembership.objects.filter(organization_id=instance.organization_id)
                .select_related("user")
                .order_by("-level", "user__email")
            )
        else:
            qs = OrganizationMembership.objects.none()

        kwargs["queryset"] = qs
        # Django's add_fields reads instance._state; provide a stub when None.
        if self.instance is None:
            self.instance = Organization()
        super(BaseInlineFormSet, self).__init__(data=data, files=files, **kwargs)

    def save(self, commit=True):
        return []


class OrganizationMemberForRelatedInline(TabularInlinePaginated):
    """Read-only inline showing OrganizationMembership on Team/Project pages.

    Both Team and Project have a FK to Organization, but
    OrganizationMembership's FK also points to Organization — not Team/Project.
    We bypass Django's FK validation and build the formset manually.
    """

    model = OrganizationMembership
    fk_name = "organization"
    template = "admin/edit_inline/readonly_tabular.html"
    extra = 0
    per_page = 20
    pagination_key = "page-member"
    verbose_name = "organization member"
    verbose_name_plural = "organization members"

    fields = ("user_link", "role", "joined_at")
    readonly_fields = ("user_link", "role", "joined_at")

    can_delete = False
    max_num = 0

    @admin.display(description="User")
    def user_link(self, membership: OrganizationMembership) -> str:
        url = reverse("admin:posthog_user_change", args=[membership.user_id])
        return format_html('<a href="{}">{}</a>', url, membership.user.email)

    @admin.display(description="Role")
    def role(self, membership: OrganizationMembership) -> str:
        return membership.get_level_display()

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_formset(self, request, obj=None, **kwargs):
        # Build formset class manually, bypassing inlineformset_factory's FK check.
        formset_cls = modelformset_factory(
            OrganizationMembership,
            form=_ReadOnlyForm,
            formset=_OrganizationMemberFormSet,
            fields=(),
            extra=0,
            max_num=self.max_num,
            can_delete=False,
        )
        formset_cls.fk = _ORGANIZATION_FK  # type: ignore[attr-defined]
        return formset_cls

    @classmethod
    def check(cls, **kwargs):
        # Skip the standard InlineModelAdmin checks which validate FK relationships.
        return []
