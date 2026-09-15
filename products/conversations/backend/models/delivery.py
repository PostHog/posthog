from __future__ import annotations

import json
from collections.abc import Iterable

from django.db import models
from django.db.models.base import ModelBase
from django.db.models.functions import Cast
from django.db.models.lookups import LessThanOrEqual
from django.utils import timezone
from django.utils.functional import Promise

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

DELIVERY_SNAPSHOT_MAX_BYTES = 256 * 1024
DELIVERY_ERROR_MAX_LENGTH = 1024


class DeliverySnapshotTooLargeError(ValueError):
    def __init__(self, field: str, payload_bytes: int) -> None:
        self.field = field
        self.payload_bytes = payload_bytes
        super().__init__(
            f"Delivery {field} is {payload_bytes} bytes; max is {DELIVERY_SNAPSHOT_MAX_BYTES}",
        )


class ConversationDeliveryChannel(models.TextChoices):
    # Values match Channel so a ticket's channel can be stored without remapping.
    SLACK = "slack", "Slack"


def conversation_delivery_channel_choices() -> list[tuple[str, str | Promise]]:
    return list(ConversationDeliveryChannel.choices)


def reject_oversized_delivery_snapshot(snapshot: object | None, *, field: str) -> None:
    if snapshot is None:
        return
    encoded = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    if len(encoded) > DELIVERY_SNAPSHOT_MAX_BYTES:
        raise DeliverySnapshotTooLargeError(field, len(encoded))


def _snapshot_size_constraint(field: str, *, name: str) -> models.CheckConstraint:
    return models.CheckConstraint(
        condition=models.Q(**{f"{field}__isnull": True})
        | models.Q(
            LessThanOrEqual(
                models.Func(
                    Cast(models.F(field), output_field=models.TextField()),
                    function="octet_length",
                    output_field=models.IntegerField(),
                ),
                models.Value(DELIVERY_SNAPSHOT_MAX_BYTES),
            ),
        ),
        name=name,
    )


def _processing_lease_constraint(*, name: str) -> models.CheckConstraint:
    # A processing row with a null lease never matches lease_expires_at <= now, so the
    # sweeper cannot reclaim it.
    return models.CheckConstraint(
        condition=~models.Q(status="processing") | models.Q(lease_expires_at__isnull=False),
        name=name,
    )


_TERMINAL_STATUS_VALUES = ["accepted", "delivered", "failed"]
_OPEN_STATUS_VALUES = ["pending", "processing"]


def _terminal_at_constraint(*, name: str) -> models.CheckConstraint:
    # Also rejects any status outside the two lists.
    return models.CheckConstraint(
        condition=models.Q(status__in=_TERMINAL_STATUS_VALUES, terminal_at__isnull=False)
        | models.Q(status__in=_OPEN_STATUS_VALUES, terminal_at__isnull=True),
        name=name,
    )


def _snapshot_gc_condition() -> models.Q:
    return models.Q(status__in=_TERMINAL_STATUS_VALUES) & (
        models.Q(payload__isnull=False) | models.Q(route__isnull=False)
    )


class DeliveryQueueRowMixin(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        ACCEPTED = "accepted", "Accepted"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    TERMINAL_STATUSES = (Status.ACCEPTED, Status.DELIVERED, Status.FAILED)

    status = models.CharField(max_length=32, choices=Status, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    due_at = models.DateTimeField(default=timezone.now)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    fencing_token = models.PositiveBigIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error = models.CharField(max_length=DELIVERY_ERROR_MAX_LENGTH, blank=True, default="")
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(null=True, blank=True)
    route = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    terminal_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if update_fields is not None:
            update_fields = {*update_fields, "updated_at"}
        terminal_at_changed = False
        if self.status in self.TERMINAL_STATUSES and self.terminal_at is None:
            self.terminal_at = timezone.now()
            terminal_at_changed = True
        elif self.status not in self.TERMINAL_STATUSES and self.terminal_at is not None:
            self.terminal_at = None
            terminal_at_changed = True
        if terminal_at_changed and update_fields is not None:
            update_fields = {*update_fields, "terminal_at"}
        if self.last_error:
            self.last_error = self.last_error[:DELIVERY_ERROR_MAX_LENGTH]
        if update_fields is None or "payload" in update_fields:
            reject_oversized_delivery_snapshot(self.payload, field="payload")
        if update_fields is None or "route" in update_fields:
            reject_oversized_delivery_snapshot(self.route, field="route")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class ConversationDelivery(DeliveryQueueRowMixin, TeamScopedRootMixin, UUIDModel):
    """Durable outbound delivery for one comment on one channel.

    PostgreSQL is the retry and provider-correlation control plane. ClickHouse is not.
    ``team`` is the canonical root team used for scoping and deduplication.
    Ticket and comment are UUID references, not foreign keys, so delivery writes
    do not take locks on ``posthog_comment`` or ``posthog_conversations_ticket``.
    Sweepers and other work outside a request must use ``objects.unscoped()`` or
    ``objects.for_team(...)``; bare ``objects.all()`` raises ``TeamScopeError``.
    Database constraints keep snapshots and terminal timestamps valid on bulk writes.
    """

    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team table on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    channel = models.CharField(max_length=32, choices=conversation_delivery_channel_choices)
    comment_id = models.UUIDField()
    ticket_id = models.UUIDField(null=True, blank=True)
    provider_account_id = models.CharField(max_length=255)

    class Meta:
        db_table = "posthog_conversations_delivery"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "channel", "comment_id"],
                name="unique_delivery_per_comment_channel",
            ),
            # Target for the part composite FK so a part cannot point at another team's delivery.
            models.UniqueConstraint(
                fields=["id", "team"],
                name="unique_delivery_id_team",
            ),
            models.CheckConstraint(
                condition=~models.Q(channel=""),
                name="delivery_channel_not_empty",
            ),
            models.CheckConstraint(
                condition=~models.Q(provider_account_id=""),
                name="delivery_provider_id_not_empty",
            ),
            _snapshot_size_constraint("route", name="delivery_route_size"),
            _snapshot_size_constraint("payload", name="delivery_payload_size"),
            _processing_lease_constraint(name="delivery_processing_has_lease"),
            _terminal_at_constraint(name="delivery_terminal_at"),
        ]
        indexes = [
            models.Index(
                fields=["due_at"],
                name="conv_delivery_pending_idx",
                condition=models.Q(status="pending"),
            ),
            models.Index(
                fields=["lease_expires_at"],
                name="conv_delivery_lease_idx",
                condition=models.Q(status="processing"),
            ),
            models.Index(
                fields=["terminal_at"],
                name="conv_delivery_terminal_idx",
                condition=models.Q(status__in=_TERMINAL_STATUS_VALUES),
            ),
            models.Index(
                fields=["terminal_at"],
                name="conv_delivery_payload_gc_idx",
                condition=_snapshot_gc_condition(),
            ),
        ]

    def __str__(self) -> str:
        return f"ConversationDelivery({self.channel}:{self.comment_id} status={self.status})"


class ConversationDeliveryPart(DeliveryQueueRowMixin, TeamScopedRootMixin, UUIDModel):
    """Retry unit for one step of an outbound delivery.

    ``part_key`` is stable across retries (``body``, an attachment identity, or
    ``fallback``). Attachment bytes stay in object storage; ``payload`` holds a
    reference, never the bytes. Claim, lease, and fencing live on this row so a
    failed image cannot resend an accepted body.
    ``delivery.parts`` is fail-closed like every other queryset on this model;
    workers without team context must use ``objects.unscoped()``.
    """

    # db_constraint=False: same hot-table reason as ConversationDelivery.team. The
    # team_id index stays because unique (delivery, part_key) does not lead with team.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="+",
    )
    # db_index=False: unique (delivery, part_key) already leads with delivery_id.
    delivery = models.ForeignKey(
        ConversationDelivery,
        on_delete=models.CASCADE,
        related_name="parts",
        db_index=False,
    )
    part_key = models.CharField(max_length=128)
    client_msg_id = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "posthog_conversations_delivery_part"
        constraints = [
            models.UniqueConstraint(
                # No team here: a mismatched team_id must not insert a second body.
                # The composite FK (delivery_id, team_id) in 0069 enforces team match.
                fields=["delivery", "part_key"],
                name="unique_delivery_part_per_key",
            ),
            models.CheckConstraint(
                condition=~models.Q(part_key=""),
                name="delivery_part_key_not_empty",
            ),
            _snapshot_size_constraint("route", name="delivery_part_route_size"),
            _snapshot_size_constraint("payload", name="delivery_part_payload_size"),
            _processing_lease_constraint(name="delivery_part_processing_has_lease"),
            _terminal_at_constraint(name="delivery_part_terminal_at"),
        ]
        indexes = [
            models.Index(
                fields=["due_at"],
                name="conv_dpart_pending_idx",
                condition=models.Q(status="pending"),
            ),
            models.Index(
                fields=["lease_expires_at"],
                name="conv_dpart_lease_idx",
                condition=models.Q(status="processing"),
            ),
            models.Index(
                fields=["terminal_at"],
                name="conv_dpart_terminal_idx",
                condition=models.Q(status__in=_TERMINAL_STATUS_VALUES),
            ),
            models.Index(
                fields=["terminal_at"],
                name="conv_dpart_payload_gc_idx",
                condition=_snapshot_gc_condition(),
            ),
        ]

    def __str__(self) -> str:
        return f"ConversationDeliveryPart({self.delivery_id}:{self.part_key} status={self.status})"
