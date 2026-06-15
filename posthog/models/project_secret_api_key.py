from typing import Optional

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ObjectDoesNotExist
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

    # Gateway this key binds to; its slug is the $ai_gateway_slug attribution value.
    # SET_NULL: deleting a gateway (or its team) just unbinds; the "drain bindings
    # first" rule is enforced at the gateway destroy endpoint, not the DB.
    gateway = models.ForeignKey(
        "posthog.Gateway",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_secret_api_keys",
    )

    class Meta:
        db_table = "posthog_projectsecretapikey"
        indexes = [models.Index(fields=["team", "created_at"])]
        constraints = [models.UniqueConstraint(fields=["team", "label"], name="unique_team_label")]

    def save(self, *args, **kwargs):
        # A gateway is project-scoped (bound to the canonical/parent team), so a
        # key in a child environment may bind its project's gateway, but a key
        # must never route through another team's gateway and misattribute spend.
        if self.gateway_id is not None:
            try:
                gateway_team_id = self.gateway.team_id
            except ObjectDoesNotExist:
                raise ValueError(f"Gateway {self.gateway_id} does not exist.")
            key_canonical_team_id = self.team.parent_team_id or self.team_id
            if gateway_team_id != key_canonical_team_id:
                raise ValueError("A project secret key and its gateway must belong to the same team.")
        super().save(*args, **kwargs)


def find_project_secret_api_key(token: str) -> Optional["ProjectSecretAPIKey"]:
    secure_value = hash_key_value(token)
    try:
        return ProjectSecretAPIKey.objects.select_related("team").get(secure_value=secure_value)
    except ProjectSecretAPIKey.DoesNotExist:
        return None
