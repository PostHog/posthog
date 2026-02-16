from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from posthog.redis import get_client
from posthog.workos_radar import WORKOS_RADAR_BYPASS_REDIS_KEY, add_radar_bypass_email, remove_radar_bypass_email


class AddBypassEmailForm(forms.Form):
    email = forms.EmailField(help_text="Email address to bypass suspicious signup checks")


def radar_bypass_view(request):
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        if "remove_email" in request.POST:
            email = request.POST["remove_email"]
            remove_radar_bypass_email(email)
            messages.success(request, f"Removed {email} from bypass list.")
            return redirect("radar-bypass")

        form = AddBypassEmailForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            add_radar_bypass_email(email)
            messages.success(request, f"Added {email} to bypass list.")
            return redirect("radar-bypass")
    else:
        form = AddBypassEmailForm()

    bypass_emails = sorted(
        member.decode() if isinstance(member, bytes) else member
        for member in get_client().smembers(WORKOS_RADAR_BYPASS_REDIS_KEY)
    )

    context = {
        "form": form,
        "bypass_emails": bypass_emails,
        "title": "Suspicious signup checks bypass",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/radar_bypass.html", context)
