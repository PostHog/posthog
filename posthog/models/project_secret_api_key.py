from typing import Optional

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import CreatedMetaFields

from .utils import generate_random_token, hash_key_value


class ProjectSecretAPIKey(ModelActivityMixin, CreatedMetaFields, models.Model):
    """
    API key tied to a project. Behaves in the same way as a PersonalAPIKey,
    but isn't tied to a single user.

    Scopes grant project-wide access within their resource type. PSAKs do not
    honor object-level access controls like per-resource RBAC restrictions.

    Intended to be used only by endpoints that should be hit programmatically
    and that need to remain accessible even when a user leaves a project.

    For example, products like Endpoints, Error tracking, or Feature flags.
    """

    objects: models.Manager["ProjectSecretAPIKey"]

    id = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="project_secret_api_keys",
    )
    label = models.CharField(max_length=40)
    mask_value = models.CharField(max_length=11, editable=False, null=True)
    secure_value = models.CharField(
        unique=True,
        max_length=300,
        null=True,
        editable=False,
    )

    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_rolled_at = models.DateTimeField(null=True, blank=True)

    scopes: ArrayField = ArrayField(models.CharField(max_length=100), null=True)

    class Meta:
        db_table = "posthog_projectsecretapikey"
        indexes = [
            models.Index(fields=["team", "created_at"]),
            # `scopes` is filtered with the array `@>` operator (scopes__contains) on
            # the gateway-credential refresh; GIN makes it an index scan, not a seq scan.
            GinIndex(fields=["scopes"], name="projectsecretapikey_scopes_gin"),
        ]
        constraints = [models.UniqueConstraint(fields=["team", "label"], name="unique_team_label")]


def find_project_secret_api_key(token: str) -> Optional["ProjectSecretAPIKey"]:
    secure_value = hash_key_value(token)
    try:
        return ProjectSecretAPIKey.objects.select_related("team").get(secure_value=secure_value)
    except ProjectSecretAPIKey.DoesNotExist:
        return None


class RevokedTeamSecretToken(models.Model):
    """Hash of a legacy team secret token whose migrated PSAK mirror row (#63111) was
    deleted by leak revocation. The pre-drop rerun of the backfill reads these, so a
    leaked token that was never rotated does not get a fresh mirror row.

    TeamScopedManager without RootTeamMixin: tokens are environment-scoped, and the
    canonical-team save() rewrite would file a child environment's hash under its root.
    """

    # db_constraint=False: a real FK to the hot posthog_team table needs a parent lock
    # to create. ORM-level CASCADE still removes rows when the team goes.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="revoked_secret_token_hashes",
        db_constraint=False,
    )
    secure_value = models.CharField(max_length=300, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now)

    objects = TeamScopedManager["RevokedTeamSecretToken"]()

    class Meta:
        db_table = "posthog_revokedteamsecrettoken"


def delete_project_secret_api_keys_for_token(team_id: int, token: str) -> None:
    """A PSAK row whose hash equals a retired legacy token IS that credential: it must
    stop authenticating when the token does (#63111 backfill)."""
    ProjectSecretAPIKey.objects.filter(team_id=team_id, secure_value=hash_key_value(token)).delete()
