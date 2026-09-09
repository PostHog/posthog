from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.db import models
from django.db.models.functions import Cast
from django.db.models.lookups import LessThanOrEqual
from django.utils import timezone
from django.utils.functional import Promise

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

INBOUND_PAYLOAD_MAX_BYTES = 256 * 1024
INBOUND_ERROR_MAX_LENGTH = 1024
# Terminal rows drop payload after this interval and remain as compact dedupe keys.
INBOUND_PAYLOAD_TTL = timedelta(hours=24)
INBOUND_TOMBSTONE_TTL = timedelta(days=30)


class InboundPayloadTooLargeError(ValueError):
    def __init__(self, payload_bytes: int) -> None:
        self.payload_bytes = payload_bytes
        super().__init__(
            f"Inbound event payload is {payload_bytes} bytes; max is {INBOUND_PAYLOAD_MAX_BYTES}",
        )


class ConversationInboundEventSource(models.TextChoices):
    SLACK_EVENTS = "slack_events", "Slack Events API"
    SLACK_INTERACTIVITY = "slack_interactivity", "Slack interactivity"


def conversation_inbound_event_source_choices() -> list[tuple[str, str | Promise]]:
    return list(ConversationInboundEventSource.choices)


def reject_oversized_inbound_payload(payload: object | None) -> None:
    if payload is None:
        return
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > INBOUND_PAYLOAD_MAX_BYTES:
        raise InboundPayloadTooLargeError(len(encoded))


class ConversationInboundEvent(TeamScopedRootMixin, UUIDModel):
    """Durable receipt for an accepted inbound provider callback.

    PostgreSQL is the acknowledgement and retry control plane. ClickHouse is not.
    ``team`` is the canonical root team used for scoping and deduplication.
    ``provider_account_id`` preserves the provider workspace or account identity.
    Sweepers and other work outside a request must use ``objects.unscoped()`` or
    ``objects.for_team(...)``; bare ``objects.all()`` raises ``TeamScopeError``.
    Database constraints keep payload and terminal timestamps valid on bulk writes.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    TERMINAL_STATUSES = (Status.PROCESSED, Status.FAILED)

    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team table on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
    )
    source = models.CharField(max_length=32, choices=conversation_inbound_event_source_choices)
    source_id = models.CharField(max_length=512)
    provider_account_id = models.CharField(max_length=255)
    provider_retry_num = models.PositiveIntegerField(null=True, blank=True)
    provider_retry_reason = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=32, choices=Status, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    due_at = models.DateTimeField(default=timezone.now)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    fencing_token = models.PositiveBigIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error = models.CharField(max_length=INBOUND_ERROR_MAX_LENGTH, blank=True, default="")
    ticket_id = models.UUIDField(null=True, blank=True)
    comment_id = models.UUIDField(null=True, blank=True)
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    terminal_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_conversations_inbound_event"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source", "source_id"],
                name="unique_inbound_event_per_source",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_id=""),
                name="inbound_event_source_id_not_empty",
            ),
            models.CheckConstraint(
                condition=~models.Q(provider_account_id=""),
                name="inbound_event_provider_id_not_empty",
            ),
            models.CheckConstraint(
                condition=models.Q(payload__isnull=True)
                | models.Q(
                    LessThanOrEqual(
                        models.Func(
                            Cast(models.F("payload"), output_field=models.TextField()),
                            function="octet_length",
                            output_field=models.IntegerField(),
                        ),
                        models.Value(INBOUND_PAYLOAD_MAX_BYTES),
                    ),
                ),
                name="inbound_event_payload_size",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["processed", "failed"],
                    terminal_at__isnull=False,
                )
                | models.Q(
                    status__in=["pending", "processing"],
                    terminal_at__isnull=True,
                ),
                name="inbound_event_terminal_at",
            ),
        ]
        indexes = [
            models.Index(
                fields=["due_at"],
                name="conv_inbound_pending_idx",
                condition=models.Q(status="pending"),
            ),
            models.Index(
                fields=["lease_expires_at"],
                name="conv_inbound_lease_idx",
                condition=models.Q(status="processing"),
            ),
            models.Index(
                fields=["terminal_at"],
                name="conv_inbound_terminal_idx",
                condition=models.Q(status__in=["processed", "failed"]),
            ),
            models.Index(
                fields=["terminal_at"],
                name="conv_inbound_payload_gc_idx",
                condition=models.Q(
                    status__in=["processed", "failed"],
                    payload__isnull=False,
                ),
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = {*update_fields, "updated_at"}
            kwargs["update_fields"] = update_fields
        terminal_at_changed = False
        if self.status in self.TERMINAL_STATUSES and self.terminal_at is None:
            self.terminal_at = timezone.now()
            terminal_at_changed = True
        elif self.status not in self.TERMINAL_STATUSES and self.terminal_at is not None:
            self.terminal_at = None
            terminal_at_changed = True
        if terminal_at_changed and update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "terminal_at"}
        if self.last_error:
            self.last_error = self.last_error[:INBOUND_ERROR_MAX_LENGTH]
        if update_fields is None or "payload" in update_fields:
            reject_oversized_inbound_payload(self.payload)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"ConversationInboundEvent({self.source}:{self.source_id} status={self.status})"
