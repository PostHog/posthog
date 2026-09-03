from django.db import models

from posthog.models.utils import uuid7


class ContextLayerConfig(models.Model):
    """One row per organization with the context layer enabled.

    `head_sha` is the compare-and-swap pointer to the current repo bundle in
    object storage; every landing writer updates it with
    `UPDATE ... WHERE head_sha = <expected>` so a lost race is explicit.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="+",
        db_constraint=False,
    )
    head_sha = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Nightly dreaming lane state: skip-overlap bookkeeping and a per-org
    # circuit breaker that pauses the lane after repeated dispatch failures.
    last_dream_started_at = models.DateTimeField(null=True, blank=True)
    dream_failure_streak = models.PositiveIntegerField(default=0)
    dreaming_paused = models.BooleanField(default=False)

    # Set when a purge rewrote the history but could not remove every old
    # bundle; cleared by the next fully successful purge.
    purge_incomplete_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "context_layer_config"
