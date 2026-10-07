"""Save-time table-access check for an edit to an insight or dashboard that other people see
through a public link or a subscription.

Neither route checks the viewer's own table access, so the person who changes what the viewers
see must be able to run the new query. The check is the compile core in `query_access_check`;
this module decides when an edit needs it and says why in the message.
"""

from typing import Any

from rest_framework import serializers

from posthog.api.query_access_check import blocked_access_for_user
from posthog.api.sharing_publish_gate import is_publicly_shared
from posthog.constants import AvailableFeature
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.facade.api import subscription_delivers_insight, subscription_delivers_whole_dashboard
from products.product_analytics.backend.facade.models import Insight


def reason_edit_needs_access_check(artifact: "Dashboard | Insight") -> str | None:
    """Why an edit to this artifact must pass the editor's table-access check, as a clause that
    completes a validation message. None when the edit needs no check.

    A public link and a subscription both show the artifact's results to people whose own table
    access is never checked. An edit that changes what they see must therefore be checked on the
    editor.
    """
    noun = "insight" if isinstance(artifact, Insight) else "dashboard"
    if is_publicly_shared(artifact):
        return f"this {noun} is publicly shared"
    if isinstance(artifact, Insight):
        delivered = subscription_delivers_insight(team_id=artifact.team_id, insight_id=artifact.id)
    else:
        delivered = subscription_delivers_whole_dashboard(team_id=artifact.team_id, dashboard_id=artifact.id)
    return f"a subscription delivers this {noun}" if delivered else None


def check_can_add_insight_to_shared_or_subscribed_dashboard(
    user: User,
    dashboard: Dashboard,
    query: Any,
    user_access_control: UserAccessControl | None = None,
) -> None:
    """Raise if binding an insight with this query to the dashboard would expose, through the
    dashboard's public link or a subscription that delivers the whole dashboard, a query the
    editor can't run themselves. No-op when the dashboard has neither, the org lacks the access
    control entitlement, or the editor is an org admin."""
    if not isinstance(query, dict):
        return
    if not dashboard.team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return
    uac = user_access_control or UserAccessControl(user=user, team=dashboard.team)
    # org admins have full access, so skip the gate for a faster write
    if uac.is_organization_admin:
        return
    reason = reason_edit_needs_access_check(dashboard)
    if reason is None:
        return
    blocked = blocked_access_for_user(user, dashboard.team, [query])
    if blocked:
        blocked_list = ", ".join(f"`{name}`" for name in blocked)
        raise serializers.ValidationError(
            f"Can't add this insight: you don't have access to {blocked_list}, and {reason}."
        )
