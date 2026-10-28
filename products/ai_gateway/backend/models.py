from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import uuid7

from .facade.enums import DevTokenClient


class DevGatewayToken(TeamScopedRootMixin):
    """`team` is the team whose wallet pays (DEV_GATEWAY_TEAM_ID), not the user's current
    project. Only the token's sha256 is stored; the bearer is returned once at mint.
    A row exists from before the gateway call, so a concurrent mint counts it against
    the daily cap; a mint the gateway refused deletes it. The foreign keys skip the DB constraint so
    creating this table takes no lock on posthog_team or posthog_user; Django still cascades.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    client = models.CharField(max_length=16, choices=DevTokenClient.choices)
    cap_usd = models.DecimalField(max_digits=10, decimal_places=2)
    token_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team", "user", "created_at"], name="ai_gw_devtoken_user_created")]

    def __str__(self) -> str:
        return f"DevGatewayToken({self.id})"
