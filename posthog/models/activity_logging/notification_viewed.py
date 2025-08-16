from django.db import models

from posthog.models.utils import UUIDTModel


class NotificationViewed(UUIDTModel):
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL)
    # when viewing notifications made by viewing the activity log we count unread notifications
    # as any after the last viewed date
    last_viewed_activity_date = models.DateTimeField(default=None)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user"], name="posthog_user_unique_viewed_date")]
