from django import forms
from django.contrib import admin
from django.http import HttpRequest

from products.account_audits.backend.models import AccountAuditCredential


class AccountAuditCredentialForm(forms.ModelForm):
    class Meta:
        model = AccountAuditCredential
        fields = ("is_active",)
        help_texts = {
            "is_active": "Disable to revoke access. To rotate, configure the workflow with a new credential before disabling this one.",
        }


# Creating a credential lives in PostHog Admin, which shows the signing secret once. The add URL redirects there.
@admin.register(AccountAuditCredential)
class AccountAuditCredentialAdmin(admin.ModelAdmin):
    form = AccountAuditCredentialForm
    fields = ("public_key_id", "created_by", "is_active", "created_at")
    readonly_fields = ("public_key_id", "created_by", "created_at")
    list_display = ("public_key_id", "created_by", "is_active", "created_at")
    list_filter = ("is_active",)
    list_select_related = ("created_by",)
    search_fields = ("public_key_id", "created_by__email")
    actions = None

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AccountAuditCredential | None = None) -> bool:
        return False
