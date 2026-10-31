import base64
import secrets

from django import forms
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse

from posthog.utils import absolute_uri

from products.account_audits.backend.models import AccountAuditCredential


class AccountAuditCredentialForm(forms.ModelForm):
    class Meta:
        model = AccountAuditCredential
        fields = ("is_active",)
        help_texts = {
            "is_active": "Disable to revoke access. To rotate, configure the workflow with a new credential before disabling this one.",
        }


@admin.register(AccountAuditCredential)
class AccountAuditCredentialAdmin(admin.ModelAdmin):
    form = AccountAuditCredentialForm
    readonly_fields = ("public_key_id", "created_by", "created_at")
    list_display = ("public_key_id", "created_by", "is_active", "created_at")
    list_filter = ("is_active",)
    list_select_related = ("created_by",)
    search_fields = ("public_key_id", "created_by__email")
    actions = None

    def get_fields(self, request: HttpRequest, obj: AccountAuditCredential | None = None) -> tuple[str, ...]:
        if obj is None:
            return ("is_active",)
        return ("public_key_id", "created_by", "is_active", "created_at")

    def has_delete_permission(self, request: HttpRequest, obj: AccountAuditCredential | None = None) -> bool:
        return False

    def save_model(
        self, request: HttpRequest, obj: AccountAuditCredential, form: forms.ModelForm, change: bool
    ) -> None:
        if not change:
            obj.created_by_id = request.user.pk
            obj.signing_secret = f"whsec_{base64.b64encode(secrets.token_bytes(32)).decode()}"
        super().save_model(request, obj, form, change)

    def response_add(
        self, request: HttpRequest, obj: AccountAuditCredential, post_url_continue: str | None = None
    ) -> HttpResponse:
        return TemplateResponse(
            request,
            "admin/account_audits/account_audit_credential_created.html",
            {
                **self.admin_site.each_context(request),
                "title": "Account audit credential created",
                "opts": self.model._meta,
                "key_id": obj.public_key_id,
                "signing_secret": obj.signing_secret,
                "credential_url": reverse("admin:account_audits_accountauditcredential_change", args=[obj.pk]),
                "api_url": absolute_uri(reverse("account_audits-start")),
            },
        )
