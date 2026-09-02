"""Shared implementation of the ticket API called by CDP workflow actions.

Two routes wrap these handlers with different authentication: the public external route
(legacy Team.secret_api_token bearer, api/external.py) and the internal service route
(scoped service JWT, api/internal.py). The worker selects between them per environment
by config presence (#82564), so the two must behave identically.
"""

import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models import Tag, Team
from posthog.models.activity_logging.activity_log import Change, Detail, Trigger, log_activity
from posthog.models.activity_logging.model_activity import ActivityTriggerContext
from posthog.models.tag import tagify

from products.conversations.backend.api.tickets import assign_ticket
from products.conversations.backend.cache import invalidate_unread_count_cache
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Priority, Status
from products.conversations.backend.services.messages import visible_ticket_messages
from products.conversations.backend.services.sla import WEEKDAYS, compute_sla_deadline


class TicketActionUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s.value for s in Status], required=False)
    priority = serializers.ChoiceField(choices=[p.value for p in Priority], required=False)
    sla_due_at = serializers.DateTimeField(required=False, allow_null=True)
    # `sla_amount`/`sla_unit`/`sla_business_hours` are the raw workflow inputs;
    # the backend computes `sla_due_at` from them so the calculation stays
    # testable and timezone-aware. Clear still routes through `sla_due_at: null`.
    sla_amount = serializers.FloatField(required=False, min_value=0.000001)
    sla_unit = serializers.ChoiceField(choices=["minute", "hour", "day"], required=False, default="hour")
    sla_business_hours = serializers.JSONField(required=False, allow_null=True)
    snoozed_until = serializers.DateTimeField(required=False, allow_null=True)
    assignee = serializers.JSONField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=200), required=False, max_length=100)
    tags_mode = serializers.ChoiceField(choices=["add", "set", "remove"], required=False, default="add")

    def validate_sla_business_hours(self, value):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError("sla_business_hours must be an object")

        days = value.get("days")
        if not isinstance(days, list) or not days:
            raise serializers.ValidationError("sla_business_hours.days must be a non-empty list")
        unknown = [d for d in days if d not in WEEKDAYS]
        if unknown:
            raise serializers.ValidationError(f"Unknown weekday names: {unknown}")

        time_cfg = value.get("time", "any")
        if time_cfg != "any":
            if not (isinstance(time_cfg, list) and len(time_cfg) == 2):
                raise serializers.ValidationError("sla_business_hours.time must be 'any' or [start, end]")
            if not isinstance(time_cfg[0], str) or not isinstance(time_cfg[1], str):
                raise serializers.ValidationError("sla_business_hours.time entries must be HH:MM strings")
            if time_cfg[0] >= time_cfg[1]:
                raise serializers.ValidationError("sla_business_hours.time start must be strictly before end")

        tz_name = value.get("timezone") or "UTC"
        if not isinstance(tz_name, str):
            raise serializers.ValidationError("sla_business_hours.timezone must be a string")
        try:
            ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            raise serializers.ValidationError(f"Invalid timezone: {tz_name}")
        return value

    def validate(self, attrs):
        if "sla_due_at" in attrs and "sla_amount" in attrs:
            raise serializers.ValidationError(
                {"sla_amount": "Cannot set both sla_due_at and sla_amount in the same request"}
            )
        return attrs


def validate_ticket_id(ticket_id: str | uuid.UUID) -> Response | None:
    """Return an error Response if ticket_id is not a valid UUID, else None."""
    # Django's <uuid:ticket_id> converter passes uuid.UUID; uuid.UUID(uuid_obj)
    # wrongly treats it as ``hex`` and raises AttributeError.
    if isinstance(ticket_id, uuid.UUID):
        return None
    try:
        uuid.UUID(str(ticket_id))
    except (ValueError, AttributeError, TypeError):
        return Response({"error": "Invalid ticket_id format"}, status=status.HTTP_400_BAD_REQUEST)
    return None


# Header a HogFlow workflow step forwards so activity entries can attribute the change to it.
HOG_FLOW_ID_HEADER = "X-PostHog-Hog-Flow-Id"


def workflow_trigger_from_request(request: Request) -> Trigger | None:
    """Build an activity-log Trigger when the request originates from a HogFlow workflow step.

    Only the workflow id is taken from the (caller-supplied) header, and only as a well-formed
    UUID. The display name is resolved from the workflow itself on the frontend, so a token
    holder can't spoof an arbitrary workflow name into the audit log. Module boundaries keep
    conversations independent of workflows, so we can't validate id ownership here; both routes
    authenticate the caller to a single team, so the worst case is a caller pointing attribution
    at another workflow id within its own team, with no cross-team or privilege impact.
    """
    hog_flow_id = request.headers.get(HOG_FLOW_ID_HEADER)
    if not hog_flow_id:
        return None
    try:
        uuid.UUID(hog_flow_id)
    except (ValueError, TypeError):
        return None
    return Trigger(job_type="hog_flow", job_id=hog_flow_id, payload={})


# The CDP worker spreads this whole response into workflow variables and rejects the step once
# their combined size passes 5KB, so this preview has to stay small enough to be a rounding
# error against that budget. The bound counts UTF-8 bytes rather than characters so that
# multibyte text cannot quietly cost several times its length. The worker measures the budget
# after JSON encoding, which escapes quotes, newlines and control characters, so a quote-heavy
# message can still cost roughly twice the figure below.
FIRST_MESSAGE_PREVIEW_BYTES = 200

# How far down the thread to look for a message with something quotable in it. Bounded so a
# ticket that opens with a run of attachments cannot turn this into a scan of the whole thread.
FIRST_MESSAGE_CANDIDATES = 5

# Attachments arrive as markdown appended to the message body, and an inbound email carrying
# only a screenshot has no other text at all. A truncated image URL identifies nothing, so drop
# image markdown outright and keep only the label of a file or link.
_IMAGE_MARKDOWN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_MARKDOWN = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# How much of a message body those regexes are allowed to scan. They are linear on ordinary
# prose, but they restart at every bracket that opens no link, so a body of unclosed brackets
# costs O(n^2), and an inbound email may carry 50,000 characters of them. This ceiling is an
# order of magnitude wider than the preview it feeds.
FIRST_MESSAGE_SCAN_CHARS = 2000

# Taking that window can cut an attachment in half, and a fragment like `![shot.png](/uploaded`
# no longer matches the patterns above, so it would survive into the preview. This drops the
# unterminated construct a cut leaves behind. The run cannot cross a bracket, so a closed
# bracket with text after it is left alone and a log line pasted as "[2026-01-01] ERROR ..."
# survives. A window ending on the bracket itself still matches, which is why the caller
# applies this only when the body was long enough to be cut.
_PARTIAL_MARKDOWN_TAIL = re.compile(r"!?\[[^\[\]]*(?:\](?:\([^)]*)?)?$")


def _quotable_text(content: str) -> str:
    window = content[:FIRST_MESSAGE_SCAN_CHARS]
    # Only a window that actually cut the body can hold a severed construct. Applying this to a
    # whole short message would eat a trailing bracket the customer meant to type.
    if len(content) > FIRST_MESSAGE_SCAN_CHARS:
        window = _PARTIAL_MARKDOWN_TAIL.sub("", window)
    text = _LINK_MARKDOWN.sub(r"\1", _IMAGE_MARKDOWN.sub("", window))
    return " ".join(text.split())


def _truncate_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Slicing encoded bytes can land inside a character, so errors="ignore" drops the partial
    # trailing one. That can also expose the joiner of a split emoji sequence, which renders as
    # a dangling glyph, so strip any joiner the cut left at the end.
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip("‍")


def _first_message_text(team_id: int, ticket_id: str) -> str | None:
    """
    Preview of what the customer first asked, so a workflow can remind them which ticket it
    is writing about on channels that carry no email subject.

    Only the customer's own messages qualify, because a ticket can open with a team message
    such as an agent composing outbound mail or a teammate's Slack post that seeded the
    ticket, and quoting that back to the customer as "what you asked us" would be wrong.

    author_type must say "customer" explicitly. Display code elsewhere treats a missing value
    as the customer's, but a wrong guess here is emailed out, so an unlabelled message is left
    out and the workflow renders no reminder instead.
    """
    candidates = (
        visible_ticket_messages(team_id, ticket_id)
        .filter(item_context__author_type="customer")
        .exclude(content__isnull=True)
        .exclude(content="")
        # Zendesk-imported messages carry second-resolution timestamps, so created_at alone can
        # tie. Tie-breaking on id keeps the preview stable from one call to the next.
        .order_by("created_at", "id")
        .values_list("content", flat=True)[:FIRST_MESSAGE_CANDIDATES]
    )
    for content in candidates:
        quotable = _quotable_text(content or "")
        if quotable:
            return _truncate_bytes(quotable, FIRST_MESSAGE_PREVIEW_BYTES) or None
    return None


def handle_ticket_get(team: Team, ticket_id: str | uuid.UUID) -> Response:
    """Fetch a ticket's data for an already-authenticated team."""
    if error := validate_ticket_id(ticket_id):
        return error

    try:
        ticket = Ticket.objects.select_related(
            "assignment", "assignment__user", "assignment__role", "email_config"
        ).get(id=ticket_id, team_id=team.id)
    except Ticket.DoesNotExist:
        return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

    assignee = None
    assignment = getattr(ticket, "assignment", None)
    if assignment:
        assignee = {
            "id": assignment.user_id if assignment.user_id else str(assignment.role_id) if assignment.role_id else None,
            "type": "role" if assignment.role_id else "user",
            "user": {"email": assignment.user.email} if assignment.user_id and assignment.user else None,
            "role": {"name": assignment.role.name} if assignment.role_id and assignment.role else None,
        }

    session_context = ticket.session_context or {}
    tags = list(ticket.tagged_items.values_list("tag__name", flat=True))

    # Hand-built payload, deliberately: neither wrapping route is in the OpenAPI spec (plain
    # APIViews without scope_object), so the schema-drift risk behind the rule cannot occur,
    # and the wire shape must stay identical to the legacy external route while the worker
    # migrates between them (a serializer would re-format datetimes).
    return Response(  # nosemgrep: api-response-must-match-schema
        {
            "id": str(ticket.id),
            "number": ticket.ticket_number,
            "status": ticket.status,
            "priority": ticket.priority,
            "channel_source": ticket.channel_source,
            "channel_detail": ticket.channel_detail,
            "distinct_id": ticket.distinct_id,
            "created_at": ticket.created_at.isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
            "message_count": ticket.message_count,
            "last_message_at": ticket.last_message_at.isoformat() if ticket.last_message_at else None,
            "last_message_text": ticket.last_message_text,
            "first_message_text": _first_message_text(team.id, str(ticket.id)),
            "unread_team_count": ticket.unread_team_count,
            "unread_customer_count": ticket.unread_customer_count,
            "sla": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
            "snoozed_until": ticket.snoozed_until.isoformat() if ticket.snoozed_until else None,
            "assignee": assignee,
            "url": session_context.get("current_url"),
            "slack_channel_id": ticket.slack_channel_id,
            "slack_thread_ts": ticket.slack_thread_ts,
            "slack_team_id": ticket.slack_team_id,
            "email_subject": ticket.email_subject,
            "email_from": ticket.email_from,
            "email_to": ticket.email_config.from_email if ticket.email_config else None,
            "cc_participants": ticket.cc_participants,
            "tags": tags,
        }
    )


def handle_ticket_patch(request: Request, team: Team, ticket_id: str | uuid.UUID) -> Response:
    """Apply a ticket update for an already-authenticated team."""
    # When a HogFlow workflow step makes the change, it forwards its identity via
    # headers so the activity log can attribute (and link to) the workflow.
    workflow_trigger = workflow_trigger_from_request(request)

    if error := validate_ticket_id(ticket_id):
        return error

    serializer = TicketActionUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    try:
        ticket = Ticket.objects.get(id=ticket_id, team_id=team.id)
    except Ticket.DoesNotExist:
        return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

    update_fields: list[str] = []
    changes: list[Change] = []

    new_status = serializer.validated_data.get("status")
    old_status = ticket.status
    if new_status is not None:
        ticket.status = new_status
        update_fields.append("status")

        if old_status == "resolved" or new_status == "resolved":
            invalidate_unread_count_cache(team.id)

        if old_status != new_status:
            changes.append(
                Change(
                    type="Ticket",
                    field="status",
                    before=old_status,
                    after=new_status,
                    action="changed",
                )
            )

    new_priority = serializer.validated_data.get("priority")
    old_priority = ticket.priority
    if new_priority is not None:
        ticket.priority = new_priority
        update_fields.append("priority")

        if old_priority != new_priority:
            changes.append(
                Change(
                    type="Ticket",
                    field="priority",
                    before=old_priority,
                    after=new_priority,
                    action="changed",
                )
            )

    old_sla_due_at = ticket.sla_due_at
    if "sla_due_at" in serializer.validated_data:
        ticket.sla_due_at = serializer.validated_data["sla_due_at"]
        update_fields.append("sla_due_at")

        if old_sla_due_at != ticket.sla_due_at:
            changes.append(
                Change(
                    type="Ticket",
                    field="sla_due_at",
                    before=old_sla_due_at.isoformat() if old_sla_due_at else None,
                    after=ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
                    action="changed",
                )
            )
    elif "sla_amount" in serializer.validated_data:
        try:
            new_sla_due_at = compute_sla_deadline(
                now=timezone.now(),
                amount=serializer.validated_data["sla_amount"],
                unit=serializer.validated_data.get("sla_unit", "hour"),
                business_hours=serializer.validated_data.get("sla_business_hours"),
            )
        except (ValueError, RuntimeError) as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})
            return Response({"error": "Invalid SLA configuration."}, status=status.HTTP_400_BAD_REQUEST)

        ticket.sla_due_at = new_sla_due_at
        if "sla_due_at" not in update_fields:
            update_fields.append("sla_due_at")

        if old_sla_due_at != ticket.sla_due_at:
            changes.append(
                Change(
                    type="Ticket",
                    field="sla_due_at",
                    before=old_sla_due_at.isoformat() if old_sla_due_at else None,
                    after=ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
                    action="changed",
                )
            )

    old_snoozed_until = ticket.snoozed_until
    if "snoozed_until" in serializer.validated_data:
        ticket.snoozed_until = serializer.validated_data["snoozed_until"]
        update_fields.append("snoozed_until")

        if old_snoozed_until != ticket.snoozed_until:
            changes.append(
                Change(
                    type="Ticket",
                    field="snoozed_until",
                    before=old_snoozed_until.isoformat() if old_snoozed_until else None,
                    after=ticket.snoozed_until.isoformat() if ticket.snoozed_until else None,
                    action="changed",
                )
            )

            # Auto-status on snooze transitions (only when status wasn't explicitly set)
            if new_status is None:
                auto_status = None
                if old_snoozed_until is None and ticket.snoozed_until is not None:
                    auto_status = "on_hold"
                elif old_snoozed_until is not None and ticket.snoozed_until is None:
                    auto_status = "open"

                if auto_status and ticket.status != auto_status:
                    auto_old_status = ticket.status
                    ticket.status = auto_status
                    if "status" not in update_fields:
                        update_fields.append("status")
                    changes.append(
                        Change(
                            type="Ticket",
                            field="status",
                            before=auto_old_status,
                            after=auto_status,
                            action="changed",
                        )
                    )

    if update_fields:
        ticket.save(update_fields=[*update_fields, "updated_at"])

    if changes:
        try:
            log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=None,
                was_impersonated=False,
                item_id=str(ticket.id),
                scope="Ticket",
                activity="updated",
                detail=Detail(
                    name=f"Ticket #{ticket.ticket_number}",
                    changes=changes,
                    trigger=workflow_trigger,
                ),
            )
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})

    if "assignee" in serializer.validated_data:
        try:
            assign_ticket(
                ticket=ticket,
                assignee=serializer.validated_data.get("assignee"),
                organization=team.organization,
                user=None,
                team_id=team.id,
                was_impersonated=False,
                trigger=workflow_trigger,
            )
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})
            return Response({"error": "Failed to assign ticket"}, status=status.HTTP_400_BAD_REQUEST)

    if "tags" in serializer.validated_data:
        try:
            tags_mode = serializer.validated_data.get("tags_mode", "add")
            normalized_tags = {tagify(t) for t in serializer.validated_data["tags"]}

            # Tag adds and removes are both logged by the TaggedItem model activity signal
            # (to the ticket's timeline and the Tag audit stream). Removals must go through
            # the per-instance delete() so the signal fires for them too; a bulk queryset
            # delete would skip it. The trigger context attributes every resulting entry
            # to the workflow that made the change.
            with ActivityTriggerContext(workflow_trigger):
                if tags_mode == "remove":
                    for tagged_item in ticket.tagged_items.filter(tag__name__in=normalized_tags).select_related(
                        "tag__team", "ticket"
                    ):
                        tagged_item.delete()
                    Tag.objects.filter(team_id=team.id, tagged_items__isnull=True).delete()
                elif tags_mode == "set":
                    for tag_name in normalized_tags:
                        tag_instance, _ = Tag.objects.get_or_create(name=tag_name, team_id=team.id)
                        ticket.tagged_items.get_or_create(tag_id=tag_instance.id)
                    for tagged_item in ticket.tagged_items.exclude(tag__name__in=normalized_tags).select_related(
                        "tag__team", "ticket"
                    ):
                        tagged_item.delete()
                    Tag.objects.filter(team_id=team.id, tagged_items__isnull=True).delete()
                else:
                    for tag_name in normalized_tags:
                        tag_instance, _ = Tag.objects.get_or_create(name=tag_name, team_id=team.id)
                        ticket.tagged_items.get_or_create(tag_id=tag_instance.id)
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})
            return Response({"error": "Failed to update tags"}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"ok": True})
