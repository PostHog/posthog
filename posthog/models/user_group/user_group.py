from django.db import models

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDTModel

# !!! DEPRECATED !!!
# Please use the ee.Role model instead


class UserGroup(UUIDTModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="user_groups")
    name = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    members = models.ManyToManyField(
        "posthog.User",
        through="posthog.UserGroupMembership",
    )


class UserGroupMembership(UUIDTModel):
    group = models.ForeignKey(UserGroup, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "user"], name="unique_per_user_per_group"),
        ]
