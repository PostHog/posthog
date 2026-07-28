"""
Django models for cookie_banner.

Keep models thin — artifact construction lives in artifact.py, appearance
defaults in constants.py.
"""

from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class CookieBannerConfig(TeamScopedRootMixin, UUIDModel):
    """Per-team cookie banner configuration, served to customer sites as the standalone
    /array/{token}/cookie-banner.js artifact.

    A team has at most one banner (one website, one consent surface), hence the
    OneToOneField. `appearance` stores only the keys the user overrides; defaults
    are merged in at delivery time (see artifact.py) so we can evolve them
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


@receiver(post_save, sender=CookieBannerConfig)
@receiver(post_delete, sender=CookieBannerConfig)
def cookie_banner_config_changed(sender: type, instance: "CookieBannerConfig", **kwargs: object) -> None:
    # models.py loads at django.setup(); importing the task chain there would drag
    # celery + the artifact builder (with its inlined art) onto the setup path
    from products.cookie_banner.backend.tasks import sync_project_cookie_banner_artifacts  # noqa: PLC0415

    transaction.on_commit(lambda: sync_project_cookie_banner_artifacts.delay(instance.team_id))
