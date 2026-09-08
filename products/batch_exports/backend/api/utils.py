import posthoganalytics
from rest_framework.exceptions import PermissionDenied

from posthog.models import Team


def check_hogql_batch_exports_enabled(team: Team) -> None:
    """Raise if HogQL-powered batch exports are not enabled for the team."""
    if not posthoganalytics.feature_enabled(
        "hogql-batch-exports",
        str(team.uuid),
        groups={"organization": str(team.organization.id)},
        group_properties={
            "organization": {
                "id": str(team.organization.id),
                "created_at": team.organization.created_at,
            }
        },
        send_feature_flag_events=False,
    ):
        raise PermissionDenied("HogQL batch exports are not enabled for this team.")
