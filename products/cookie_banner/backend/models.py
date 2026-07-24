"""
Django models for cookie_banner.

Keep models thin — payload construction for remote config lives in
remote_config.py, appearance defaults in constants.py.
"""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class CookieBannerConfig(TeamScopedRootMixin, UUIDModel):
    """Per-team cookie banner configuration, delivered to customer sites via remote config.

    A team has at most one banner (one website, one consent surface), hence the
    OneToOneField. `appearance` stores only the keys the user overrides; defaults
    are merged in at delivery time (see remote_config.py) so we can evolve them
    without data migrations.
    """

    # db_constraint=False keeps CreateModel off posthog_team's lock path (hot table).
    # Tenant isolation is still enforced by the fail-closed TeamScopedRootMixin manager.
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="cookie_banner_config",
    )
    enabled = models.BooleanField(default=False)
    appearance = models.JSONField(default=dict, blank=True)
    # db_constraint=False: a real FK to the hot posthog_user table locks it on deploy.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"CookieBannerConfig for team {self.team_id}"
