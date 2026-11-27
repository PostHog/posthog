from urllib.parse import urlencode

from django import forms
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse

from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, FieldGroup, Filters, Notice, Page, Paging, Row, Table
from posthog.admin.organization_members import organization_memberships
from posthog.models.organization import Organization, OrganizationMembership

ORGANIZATION_MEMBERS_TOOL_KEY = "organization-members"
MEMBERS_PER_PAGE = 100


def organization_members_url(organization: Organization) -> str:
    tool_url = reverse("admin_console_tool", kwargs={"tool_key": ORGANIZATION_MEMBERS_TOOL_KEY})
    return f"{tool_url}?{urlencode({'organization': organization.pk})}"


class MemberSearchForm(forms.Form):
    organization = forms.UUIDField(widget=forms.HiddenInput)
    search = forms.CharField(required=False, label="Search", help_text="Part of an email address or a name.")


class OrganizationMembers:
    def __init__(self, organization: Organization, search: str) -> None:
        self.organization = organization
        self.search = search

    def memberships(self) -> QuerySet[OrganizationMembership]:
        memberships = organization_memberships(self.organization.pk)
        if not self.search:
            return memberships
        return memberships.filter(
            Q(user__email__icontains=self.search)
            | Q(user__first_name__icontains=self.search)
            | Q(user__last_name__icontains=self.search)
        )

    @staticmethod
    def row(membership: OrganizationMembership) -> Row:
        user = membership.user
        return Row(
            cells=(
                Cell(text=user.email, href=RECORD_TYPES["user"].url(user)),
                Cell(text=f"{user.first_name} {user.last_name}".strip()),
                Cell(text=OrganizationMembership.Level(membership.level).label.capitalize()),
                Cell(
                    text=user.last_login.strftime("%b %-d, %Y") if user.last_login else "Never",
                    muted=user.last_login is None,
                ),
                Cell(text=membership.joined_at.strftime("%b %-d, %Y")),
            )
        )


@console.register_tool
class OrganizationMembersTool(ConsoleTool):
    key = ORGANIZATION_MEMBERS_TOOL_KEY
    title = "Organization members"
    owner = None
    group = "Organizations"
    description = "Lists the members of one organization. Open a member to log in as them."

    def page(self, request: HttpRequest) -> Page:
        form = MemberSearchForm(request.GET)
        organization = None
        if form.is_valid():
            organization = Organization.objects.filter(pk=form.cleaned_data["organization"]).first()
        if organization is None:
            return Page(blocks=(Notice(text="Open an organization's members from the Members link on its page."),))

        members = OrganizationMembers(organization, form.cleaned_data["search"].strip())
        page = Paginator(members.memberships(), MEMBERS_PER_PAGE).get_page(request.GET.get("page"))
        query = request.GET.copy()

        def page_url(number: int) -> str:
            query["page"] = str(number)
            return f"?{query.urlencode()}"

        return Page(
            blocks=(
                Notice(
                    text=f"Members of {organization.name}, owners and admins first.",
                    link_text="Back to the organization",
                    href=RECORD_TYPES["organization"].url(organization),
                ),
                Filters(
                    form=form,
                    groups=(FieldGroup(title="Search", field_names=("search",)),),
                    submit_label="Search",
                    compact=True,
                ),
                Table(
                    columns=("Email", "Name", "Role", "Last login", "Joined"),
                    rows=tuple(OrganizationMembers.row(membership) for membership in page.object_list),
                    empty_text="No members match." if members.search else "This organization has no members.",
                ),
                *(
                    (
                        Paging(
                            number=page.number,
                            num_pages=page.paginator.num_pages,
                            summary=f"{page.paginator.count:,} members",
                            previous_url=page_url(page.previous_page_number()) if page.has_previous() else None,
                            next_url=page_url(page.next_page_number()) if page.has_next() else None,
                        ),
                    )
                    if page.paginator.count
                    else ()
                ),
            )
        )
