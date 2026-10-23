import typing

import posthoganalytics
from rest_framework.exceptions import PermissionDenied

from posthog.models import Team

from . import validation


class WorkflowsDestinationSerializer(validation.DestinationValidationSerializer):
    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        team_id = self.context["team_id"]
        team = Team.objects.get(id=team_id)

        if not posthoganalytics.feature_enabled(
            "backfill-workflows-destination",
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
            raise PermissionDenied("Backfilling Workflows is not enabled for this team.")
        return attrs
