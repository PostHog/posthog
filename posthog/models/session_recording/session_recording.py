from django.db import models
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class SessionRecording(UUIDModel):

    # Note: UUIDT is the PostHog standard, but session_id's are generated with a different util in posthog-js
    # https://github.com/PostHog/posthog-js/blob/e0dc2c005cfb5dd62b7c876676bcffe1654417a7/src/utils.ts#L457-L458
    # We create recording objects with both UUIDT and a unique session_id field to remain backwards compatible.
    # All other models related to the session recording model uses this unique `session_id` to create the link.
    session_id: models.CharField = models.CharField(unique=True, max_length=200)

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    last_modified_by: models.ForeignKey = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="modified_recordings"
    )
    deleted: models.BooleanField = models.BooleanField(default=False)

    # TODO: add metadata field to keep minimal information on this model for quick access
