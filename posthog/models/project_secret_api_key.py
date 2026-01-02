import json
from typing import TYPE_CHECKING, Optional

from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.db import models
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin

from .personal_api_key import hash_key_value
from .utils import generate_random_token

if TYPE_CHECKING:
    pass

FIVE_DAYS = 60 * 60 * 24 * 5  # 5 days in seconds


def _get_cache_key(secure_value: str) -> str:
    return f"project_secret_api_key:{secure_value}"


def _get_cached_key_data(secure_value: str) -> Optional[dict]:
    """Get cached project secret API key data."""
    try:
        cached_data = cache.get(_get_cache_key(secure_value))
        if cached_data:
            return json.loads(cached_data)
    except Exception:
        # Redis unavailable or parse error
        pass
    return None


def _set_cached_key_data(secure_value: str, key_data: dict) -> None:
    """Cache project secret API key data."""
    try:
        cache.set(_get_cache_key(secure_value), json.dumps(key_data), FIVE_DAYS)
    except Exception:
        # Redis unavailable
        pass


def invalidate_project_secret_api_key_cache(secure_value: str) -> None:
    """Invalidate the cache for a project secret API key."""
    try:
        cache.delete(_get_cache_key(secure_value))
    except Exception:
        pass


class ProjectSecretAPIKey(ModelActivityMixin, models.Model):
    """
    API key tied to a project. Behaves in the same way as a PersonalAPIKey,
    but isn't tied to a single user.

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
        indexes = [models.Index(fields=["team", "created_at"])]
        constraints = [models.UniqueConstraint(fields=["team", "label"], name="unique_team_label")]

    def save(self, *args, **kwargs):
        # Invalidate cache when key is updated (e.g., scopes changed, key rolled)
        # We need to invalidate the OLD secure_value in case it was changed (key rolled)
        if self.pk:
            try:
                old_instance = ProjectSecretAPIKey.objects.get(pk=self.pk)
                if old_instance.secure_value:
                    invalidate_project_secret_api_key_cache(old_instance.secure_value)
            except ProjectSecretAPIKey.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.secure_value:
            invalidate_project_secret_api_key_cache(self.secure_value)
        super().delete(*args, **kwargs)

    @classmethod
    def find_project_secret_api_key(cls, token) -> tuple["ProjectSecretAPIKey", str] | None:
        """
        Find a project secret API key by token value.

        Uses Redis caching with a 5-day TTL to avoid database hits on every request,
        since endpoint execution can be high-traffic.
        """
        from posthog.models.team import Team

        secure_value = hash_key_value(token, mode="sha256")

        cached_data = _get_cached_key_data(secure_value)
        if cached_data:
            try:
                team = Team(id=cached_data["team_id"], project_id=cached_data["team_id"])
                key = cls(
                    id=cached_data["id"],
                    team=team,
                    label=cached_data["label"],
                    mask_value=cached_data["mask_value"],
                    secure_value=cached_data["secure_value"],
                    scopes=cached_data.get("scopes"),
                )
                return key, "sha256"
            except Exception:
                pass

        try:
            obj = cls.objects.select_related("team").get(secure_value=secure_value)

            _set_cached_key_data(
                secure_value,
                {
                    "id": obj.id,
                    "team_id": obj.team.id,
                    "label": obj.label,
                    "mask_value": obj.mask_value,
                    "secure_value": obj.secure_value,
                    "scopes": obj.scopes,
                },
            )

            return obj, "sha256"
        except ProjectSecretAPIKey.DoesNotExist:
            return None
