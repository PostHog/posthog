import json

from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.utils import UUIDModel
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL

# Single Redis key holding the JSON blob of dynamic custom rate-limit thresholds.
# Must equal capture's GLOBAL_RATE_LIMIT_CUSTOM_THRESHOLD_KEY env var so the
# refresh loop reads what this writer produces.
CUSTOM_THRESHOLDS_REDIS_KEY = "capture_global_rate_limit_custom_thresholds"

# Keep in sync with capture's MAX_DISTINCT_ID_CHARS. Capture truncates the
# distinct_id to this many characters when building its rate-limit cache key, so
# the resolved key written here must truncate identically to match at lookup time.
MAX_DISTINCT_ID_CHARS = 128


class GlobalRateLimitThresholdConfig(UUIDModel):
    """
    Ops-managed custom per-key thresholds for the capture global rate limiter.

    Each row maps a token (optionally scoped to a single distinct_id) to a
    threshold that overrides the limiter's global default. All rows serialize to a
    single Redis key that capture refreshes on a timer. Internal ops tooling only:
    no customer-facing API or UI.
    """

    token = models.CharField(max_length=100)
    distinct_id = models.CharField(
        max_length=450,
        blank=True,
        default="",
        help_text=(
            "Optional. Empty applies the threshold to the whole token; "
            "set applies it only to this token and distinct_id."
        ),
    )
    threshold = models.PositiveBigIntegerField(help_text="Max events allowed per rate-limit window for this key.")
    note = models.TextField(blank=True, null=True, help_text="Optional note explaining why this override exists")

    class Meta:
        unique_together = ("token", "distinct_id")

    @property
    def resolved_key(self) -> str:
        """The key capture looks up: ``token`` or ``token:distinct_id`` (truncated)."""
        if self.distinct_id:
            return f"{self.token}:{self.distinct_id[:MAX_DISTINCT_ID_CHARS]}"
        return self.token


def regenerate_redis_thresholds() -> None:
    """Rebuild the Redis threshold blob from all rows; delete the key when empty."""
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)

    configs = list(GlobalRateLimitThresholdConfig.objects.all().order_by("id"))
    if not configs:
        redis_client.delete(CUSTOM_THRESHOLDS_REDIS_KEY)
        return

    thresholds = {config.resolved_key: config.threshold for config in configs}
    redis_client.set(CUSTOM_THRESHOLDS_REDIS_KEY, json.dumps(thresholds))


@receiver(post_save, sender=GlobalRateLimitThresholdConfig)
def update_redis_thresholds_on_save(sender, instance, created=False, **kwargs) -> None:
    regenerate_redis_thresholds()


@receiver(post_delete, sender=GlobalRateLimitThresholdConfig)
def update_redis_thresholds_on_delete(sender, instance, **kwargs) -> None:
    regenerate_redis_thresholds()
