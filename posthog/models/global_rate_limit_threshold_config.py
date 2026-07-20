import json

from django.db import models, transaction
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

    # Matches Team.api_token's max_length so any valid capture token can get an override.
    token = models.CharField(max_length=200)
    distinct_id = models.CharField(
        max_length=450,
        blank=True,
        default="",
        help_text=(
            "Optional. Empty applies the threshold to the whole token; "
            "set applies it only to this token and distinct_id."
        ),
    )
    threshold = models.PositiveBigIntegerField(
        help_text=(
            "Max events allowed per rate-limit window for this key. 0 rate-limits the key to zero, but the "
            "limiter is cache-based so an isolated event may still pass on a cold cache miss; to block a key "
            "permanently use an EventRestriction in the Django admin."
        )
    )
    note = models.TextField(blank=True, null=True, help_text="Optional note explaining why this override exists")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("token", "distinct_id")

    @property
    def resolved_key(self) -> str:
        """The key capture looks up: ``token`` or ``token:distinct_id`` (truncated)."""
        if self.distinct_id:
            return f"{self.token}:{self.distinct_id[:MAX_DISTINCT_ID_CHARS]}"
        return self.token


def regenerate_redis_thresholds() -> None:
    """Rebuild the Redis threshold blob from all rows.

    Writes an explicit empty blob (``{}``) when no rows remain rather than
    deleting the key: capture treats an absent key as fail-static (keeps its
    current map), so a deliberate clear must be a written state.
    """
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)

    configs = GlobalRateLimitThresholdConfig.objects.all().order_by("id")
    thresholds = {config.resolved_key: config.threshold for config in configs}
    redis_client.set(CUSTOM_THRESHOLDS_REDIS_KEY, json.dumps(thresholds))


@receiver(post_save, sender=GlobalRateLimitThresholdConfig)
def update_redis_thresholds_on_save(sender, instance, created=False, **kwargs) -> None:
    # Defer to commit: the admin wraps save_model in a transaction, so publishing
    # inside the signal would leak a threshold to capture that a rollback erases.
    transaction.on_commit(regenerate_redis_thresholds)


@receiver(post_delete, sender=GlobalRateLimitThresholdConfig)
def update_redis_thresholds_on_delete(sender, instance, **kwargs) -> None:
    transaction.on_commit(regenerate_redis_thresholds)
