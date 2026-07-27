from typing import Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.urls import URLPattern, path, reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString


class RollApiKeyAdminMixin(admin.ModelAdmin):
    """Shared "Roll" action for API key admins.

    Renders a Roll button on the change form (via the shared change_form template, which
    prompts for the URL where the key was exposed) and a POST-only view that rotates the
    key and notifies its owners. Subclasses implement `roll_and_notify` and include
    "roll_action" in `fields`/`readonly_fields`.
    """

    change_form_template = "admin/posthog/api_key/change_form.html"
    roll_success_message = "API key rolled."

    def roll_and_notify(self, key: Any, more_info: str) -> None:
        raise NotImplementedError

    def _roll_url_name(self) -> str:
        return f"{self.opts.app_label}_{self.opts.model_name}_roll"

    @admin.display(description="Roll Key")
    def roll_action(self, key: Any) -> str | SafeString:
        if not key or not key.pk:
            return ""
        return format_html(
            '<button type="submit" name="_roll" id="roll_key_button" class="button" '
            'formmethod="post" formaction="{}" formnovalidate style="padding: 5px 10px; background-color: red;">Roll</button> '
            '<input type="hidden" name="_roll_url" />',
            reverse(f"admin:{self._roll_url_name()}", args=[key.pk]),
        )

    def get_urls(self) -> list[URLPattern]:
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/roll/",
                self.admin_site.admin_view(self.roll_view),
                name=self._roll_url_name(),
            ),
        ]
        return custom + urls

    def roll_view(self, request: HttpRequest, object_id: str, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        try:
            key = self.get_queryset(request).get(pk=object_id)
        except self.model.DoesNotExist:
            return redirect(reverse(f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist"))

        url = request.POST.get("_roll_url", "")
        more_info = f"This key was detected at {url}." if url else ""

        self.roll_and_notify(key, more_info)
        self.log_change(request, key, "Rolled key.")

        self.message_user(request, self.roll_success_message)
        return redirect(reverse(f"admin:{self.opts.app_label}_{self.opts.model_name}_change", args=[key.pk]))
