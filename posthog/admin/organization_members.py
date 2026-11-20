from django.urls import reverse
from django.utils.html import format_html, format_html_join

from posthog.models.organization import OrganizationMembership

MEMBERS_SHOWN = 100


def organization_members_table(organization_id) -> str:
    memberships = (
        OrganizationMembership.objects.filter(organization_id=organization_id)
        .select_related("user")
        .order_by("-level", "user__email")
    )
    total = memberships.count()
    if not total:
        return "-"

    rows = format_html_join(
        "",
        '<tr><td><a href="{}">{}</a></td><td>{}</td><td>{}</td></tr>',
        (
            (
                reverse("admin:posthog_user_change", args=[membership.user_id]),
                membership.user.email,
                membership.get_level_display(),
                membership.joined_at.strftime("%Y-%m-%d %H:%M UTC"),
            )
            for membership in memberships[:MEMBERS_SHOWN]
        ),
    )
    table = format_html(
        "<table><thead><tr><th>User</th><th>Role</th><th>Joined</th></tr></thead><tbody>{}</tbody></table>",
        rows,
    )
    if total <= MEMBERS_SHOWN:
        return table
    return format_html(
        '{}<p>Showing {} of {} members. <a href="{}">See all on the organization page</a></p>',
        table,
        MEMBERS_SHOWN,
        total,
        reverse("admin:posthog_organization_change", args=[organization_id]),
    )
