from typing import Optional

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin

from .utils import generate_random_token, hash_key_value


class ProjectSecretAPIKey(ModelActivityMixin, models.Model):
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
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, related_name="created_project_secret_api_keys", null=True
    )
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
