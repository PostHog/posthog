from django.core.management.base import BaseCommand

from posthog.models.global_rate_limit_threshold_config import (
    CUSTOM_THRESHOLDS_REDIS_KEY,
    GlobalRateLimitThresholdConfig,
    regenerate_redis_thresholds,
)


class Command(BaseCommand):
    help = (
        "Write the capture global rate limiter's custom-threshold blob to Redis from the "
        "current GlobalRateLimitThresholdConfig rows. Normally the post_save/post_delete "
        "signals keep the blob current, but they only fire on row changes: an environment "
        "with zero rows has never written the key at all, and capture treats the absent key "
        "as fail-static (it polls forever without ever loading a map). Run this once per "
        "environment to bootstrap the key (an explicit empty blob is a valid, loadable state), "
        "or to force a resync if the key is lost."
    )

    def handle(self, *args, **options) -> None:
        row_count = GlobalRateLimitThresholdConfig.objects.count()
        regenerate_redis_thresholds()
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {row_count} threshold override(s) to Redis key {CUSTOM_THRESHOLDS_REDIS_KEY!r}")
        )
