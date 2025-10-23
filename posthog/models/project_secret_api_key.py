from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin

from .personal_api_key import hash_key_value
from .utils import generate_random_token


class ProjectSecretAPIKey(ModelActivityMixin, models.Model):
    """
    API key tied to a project. Behaves in the same way as a PersonalAPIKey,
    but isn't tied to a single user.

    Intended to be used only by endpoints that should be hit programmatically
    and that need to remain accessible even when a user leaves a project.

    For example, products like Endpoints, Error tracking, or Feature flags.
    """

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
        indexes = [models.Index(fields=["team", "created_at"])]
        constraints = [models.UniqueConstraint(fields=["team", "label"], name="unique_team_label")]

    @classmethod
    def find_project_secret_api_key(cls, token):
        secure_value = hash_key_value(token, mode="sha256")
        try:
            obj = cls.objects.select_related("team").get(secure_value=secure_value)
            return obj, "sha256"
        except ProjectSecretAPIKey.DoesNotExist:
            return None
