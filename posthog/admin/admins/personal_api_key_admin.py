from django.contrib import admin
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.models import PersonalAPIKey
from posthog.tasks.email import send_personal_api_key_exposed


class PersonalAPIKeyAdmin(admin.ModelAdmin):
    change_form_template = "admin/posthog/personal_api_key/change_form.html"

    fields = (
        "id",
        "user",
        "label",
        "created_at",
        "last_used_at",
        "last_rolled_at",
        "scopes",
        "scoped_teams",
        "scoped_organizations",
        "team",
        "roll_action",
    )
    readonly_fields = (
        "id",
        "team",
        "user",
        "roll_action",
    )
    list_display = ("id", "label", "mask_value", "user_link", "created_at", "last_used_at", "scopes")
    list_display_links = ("id", "label")
    list_select_related = ("user",)
    search_fields = ("id", "user__email", "scopes")
    autocomplete_fields = ("user", "team")
    ordering = ("-created_at",)

    @admin.display(description="User")
    def user_link(self, key: PersonalAPIKey):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_user_change", args=[key.user.pk]),
            key.user.email,
        )

    @admin.display(description="Roll Key")
    def roll_action(self, personal_api_key: PersonalAPIKey):
        if not personal_api_key or not personal_api_key.pk:
            return ""
        return format_html(
            '<button type="submit" name="_roll" id="roll_key_button" class="button" '
            'formmethod="post" formaction="{}" formnovalidate style="padding: 5px 10px; background-color: red;">Roll</button> '
            '<input type="hidden" name="_roll_url" />',
            reverse("admin:posthog_personalapikey_roll", args=[personal_api_key.pk]),
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/roll/",
                self.admin_site.admin_view(self.roll_view),
                name="posthog_personalapikey_roll",
            ),
        ]
        return custom + urls

    def roll_view(self, request, object_id, *args, **kwargs):
        personal_api_key = self.get_queryset(request).select_related("user").get(pk=object_id)
        if not personal_api_key:
            return redirect(reverse("admin:posthog_personalapikey_changelist"))
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        old_mask_value = personal_api_key.mask_value
        url = request.POST.get("_roll_url", "")
        more_info = ""
        if url != "":
            more_info = f"This key was detected at {url}."

        serializer = PersonalAPIKeySerializer(instance=personal_api_key)
        serializer.roll(personal_api_key)
        self.log_change(request, personal_api_key, f"Rolled key.")
        send_personal_api_key_exposed(personal_api_key.user.id, personal_api_key.id, old_mask_value, more_info)

        self.message_user(request, f"Personal API key rolled and user notified.")
        return redirect(reverse("admin:posthog_personalapikey_change", args=[personal_api_key.pk]))
