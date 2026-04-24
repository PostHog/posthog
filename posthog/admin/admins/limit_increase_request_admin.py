from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from posthog.models import OrganizationLimitOverride
from posthog.models.limit_increase_request import LimitIncreaseRequestStatus


class LimitIncreaseRequestApproveForm(forms.Form):
    value = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="New limit value. Leave blank to grant unlimited.",
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "style": "width: 100%;"}),
        help_text="Free-text justification from the approver. Also stored as the resolution note visible to the customer.",
    )


class LimitIncreaseRequestDenyForm(forms.Form):
    resolution_note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "style": "width: 100%;"}),
        help_text="Customer-visible explanation of why this request was denied.",
    )


class LimitIncreaseRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team",
        "limit_key",
        "status",
        "limit_at_first_hit",
        "count_at_first_hit",
        "hit_count",
        "last_hit_at",
        "created_at",
    )
    list_filter = ("status", "limit_key")
    search_fields = (
        "team__name",
        "team__id",
        "team__organization__name",
        "team__organization__id",
        "limit_key",
        "justification",
    )
    readonly_fields = (
        "team",
        "limit_key",
        "limit_at_first_hit",
        "count_at_first_hit",
        "requested_value",
        "justification",
        "status",
        "requested_by",
        "hit_count",
        "last_hit_at",
        "resolved_by",
        "resolved_at",
        "resolution_note",
        "created_at",
    )
    ordering = ("-last_hit_at",)
    autocomplete_fields = ("team", "requested_by", "resolved_by")
    change_form_template = "admin/posthog/limitincreaserequest/change_form.html"

    def has_add_permission(self, request) -> bool:
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj is not None and obj.status == LimitIncreaseRequestStatus.PENDING:
            extra_context["approve_url"] = reverse("admin:posthog_limitincreaserequest_approve", args=[obj.pk])
            extra_context["deny_url"] = reverse("admin:posthog_limitincreaserequest_deny", args=[obj.pk])
            extra_context["can_resolve"] = True
        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/approve/",
                self.admin_site.admin_view(self.approve_view),
                name="posthog_limitincreaserequest_approve",
            ),
            path(
                "<path:object_id>/deny/",
                self.admin_site.admin_view(self.deny_view),
                name="posthog_limitincreaserequest_deny",
            ),
        ]
        return custom_urls + urls

    def approve_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            return HttpResponseRedirect(reverse("admin:posthog_limitincreaserequest_changelist"))

        if obj.status != LimitIncreaseRequestStatus.PENDING:
            messages.error(request, "Only pending requests can be approved.")
            return HttpResponseRedirect(reverse("admin:posthog_limitincreaserequest_change", args=[obj.pk]))

        if request.method == "POST":
            form = LimitIncreaseRequestApproveForm(request.POST)
            if form.is_valid():
                value = form.cleaned_data["value"]
                reason = form.cleaned_data["reason"]
                with transaction.atomic():
                    OrganizationLimitOverride.objects.update_or_create(
                        team_id=obj.team_id,
                        limit_key=obj.limit_key,
                        defaults={
                            "value": value,
                            "reason": reason,
                            "granted_by": request.user,
                        },
                    )
                    obj.status = LimitIncreaseRequestStatus.APPROVED
                    obj.resolved_by = request.user
                    obj.resolved_at = timezone.now()
                    obj.resolution_note = reason
                    obj.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note"])
                self.log_change(
                    request,
                    obj,
                    "Approved with unlimited" if value is None else f"Approved with value={value}",
                )
                messages.success(
                    request,
                    f"Approved. New limit: {value if value is not None else 'unlimited'}.",
                )
                return HttpResponseRedirect(reverse("admin:posthog_limitincreaserequest_change", args=[obj.pk]))
        else:
            form = LimitIncreaseRequestApproveForm(initial={"value": obj.limit_at_first_hit * 2})

        context = {
            **self.admin_site.each_context(request),
            "obj": obj,
            "form": form,
            "opts": self.model._meta,
            "title": format_html("Approve limit increase request {}", obj.pk),
        }
        return TemplateResponse(request, "admin/posthog/limitincreaserequest/resolve.html", context)

    def deny_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            return HttpResponseRedirect(reverse("admin:posthog_limitincreaserequest_changelist"))

        if obj.status != LimitIncreaseRequestStatus.PENDING:
            messages.error(request, "Only pending requests can be denied.")
            return HttpResponseRedirect(reverse("admin:posthog_limitincreaserequest_change", args=[obj.pk]))

        if request.method == "POST":
            form = LimitIncreaseRequestDenyForm(request.POST)
            if form.is_valid():
                obj.status = LimitIncreaseRequestStatus.DENIED
                obj.resolved_by = request.user
                obj.resolved_at = timezone.now()
                obj.resolution_note = form.cleaned_data["resolution_note"]
                obj.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note"])
                self.log_change(request, obj, "Denied")
                messages.success(request, "Request denied.")
                return HttpResponseRedirect(reverse("admin:posthog_limitincreaserequest_change", args=[obj.pk]))
        else:
            form = LimitIncreaseRequestDenyForm()

        context = {
            **self.admin_site.each_context(request),
            "obj": obj,
            "form": form,
            "mode": "deny",
            "opts": self.model._meta,
            "title": format_html("Deny limit increase request {}", obj.pk),
        }
        return TemplateResponse(request, "admin/posthog/limitincreaserequest/resolve.html", context)
