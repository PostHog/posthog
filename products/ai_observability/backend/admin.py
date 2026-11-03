from typing import TYPE_CHECKING

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods

import structlog

from posthog.models.instance_setting import set_instance_setting

from products.ai_observability.backend.dataset_retention import RETENTION_ENABLED_SETTING, dataset_retention_enabled

if TYPE_CHECKING:
    from django.contrib.admin import AdminSite

logger = structlog.get_logger(__name__)


class DatasetRetentionForm(forms.Form):
    enabled = forms.TypedChoiceField(
        label="Dataset cleanup",
        choices=[("enabled", "Enabled"), ("disabled", "Disabled")],
        coerce=lambda value: value == "enabled",
        widget=forms.RadioSelect,
    )


@require_http_methods(["GET", "POST"])
def dataset_retention_view(request: HttpRequest, *, admin_site: "AdminSite") -> HttpResponse:
    if not request.user.has_perm("posthog.change_instancesetting"):
        raise PermissionDenied
    enabled = dataset_retention_enabled()
    form = DatasetRetentionForm(
        request.POST if request.method == "POST" else None, initial={"enabled": "enabled" if enabled else "disabled"}
    )
    if request.method == "POST" and form.is_valid():
        new_enabled = form.cleaned_data["enabled"]
        set_instance_setting(RETENTION_ENABLED_SETTING, new_enabled)
        logger.info(
            "dataset_retention_setting_changed", user_id=request.user.pk, previous_enabled=enabled, enabled=new_enabled
        )
        messages.success(request, f"Dataset cleanup is now {'enabled' if new_enabled else 'disabled'} in this region.")
        return redirect(reverse("admin:ai-observability-dataset-retention"))
    return TemplateResponse(
        request,
        "admin/posthog/organization/ai_observability_dataset_retention.html",
        {
            **admin_site.each_context(request),
            "title": "AI observability dataset retention",
            "form": form,
            "enabled": enabled,
        },
    )
