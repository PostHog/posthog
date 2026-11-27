from urllib.parse import urlencode

from django import forms
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Notice, Page
from posthog.models.organization import Organization


class MemberSearchForm(forms.Form):
    organization = forms.UUIDField()


@console.register_tool
class OrganizationMembersTool(ConsoleTool):
    """Links to this tool keep working. The members list is now the Members list of the organization's page."""

    key = "organization-members"
    title = "Organization members"
    owner = None
    group = "Organizations"
    description = "Lists the members of one organization. Open a member to log in as them."

    def app_page(self, request: HttpRequest) -> HttpResponse | None:
        form = MemberSearchForm(request.GET)
        if not form.is_valid():
            return None
        organization = Organization.objects.filter(pk=form.cleaned_data["organization"]).first()
        if organization is None:
            return None
        members_url = reverse(
            RECORD_TYPES["organization"].related_url_name, kwargs={"pk": organization.pk, "relation_key": "members"}
        )
        # Old bookmarks keep their search and page.
        kept = {name: request.GET[name] for name in ("search", "page") if request.GET.get(name, "").strip()}
        return HttpResponseRedirect(f"{members_url}?{urlencode(kept)}" if kept else members_url)

    def page(self, request: HttpRequest) -> Page:
        return Page(blocks=(Notice(text="Open an organization's members from the Members list on its page."),))
