"""Bounded, PII-allowlisted extras for support AI ticket context."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import unquote
from uuid import UUID

from django.db.models import CharField, Exists, OuterRef, Q
from django.db.models.functions import Cast

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.api import (
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
)
from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import OrganizationIdSource, TicketStatus
from products.conversations.backend.playbook import is_posthog_docs_source
from products.conversations.backend.services.messages import public_human_ticket_replies
from products.customer_analytics.backend.facade.api import (
    get_account,
    get_custom_property_definition,
    list_active_custom_property_values,
)

if TYPE_CHECKING:
    from posthog.models.team import Team

MAX_PRIOR_TICKETS = 3
MAX_PRIOR_TICKET_REPLY_CHARS = 600
MAX_PRIOR_TICKET_TITLE_CHARS = 120
MAX_PRIOR_TICKETS_SECTION_CHARS = 2400
MAX_SESSION_CONTEXT_SECTION_CHARS = 800
MAX_ENTITY_REFS_SECTION_CHARS = 1200
MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS = 10
MAX_ACCOUNT_PROPERTY_VALUE_CHARS = 200
MAX_ACCOUNT_SECTION_CHARS = 1500

ACCOUNT_TARGET_TYPE = "account"

_SESSION_CONTEXT_FIELDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("current_url", "url", "$current_url"), "Page"),
    (("sdk_version", "lib_version", "$lib_version"), "SDK version"),
    (("browser", "$browser"), "Browser"),
    (("browser_version", "$browser_version"), "Browser version"),
    (("os", "$os"), "OS"),
)

_FEATURE_FLAG_PATH = re.compile(r"/feature_flags/([^/?#\s]+)", re.IGNORECASE)
_INSIGHT_PATH = re.compile(r"/insights/([^/?#\s]+)", re.IGNORECASE)
_RECORDING_PATH = re.compile(
    r"/(?:replay|session-recordings|recordings)/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
    re.IGNORECASE,
)
_DASHBOARD_PATH = re.compile(r"/dashboard(?:s)?/([^/?#\s]+)", re.IGNORECASE)
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_SKIP_PATH_SEGMENTS = frozenset({"new", "edit", "history", "settings"})
_ENTITY_KIND_LABELS = {
    "feature_flag": "Feature flag",
    "insight": "Insight",
    "recording": "Recording",
    "dashboard": "Dashboard",
    "uuid": "UUID",
}


@frozen
class PriorTicket:
    ticket_number: int
    title: str
    reply: str


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."


def _capped_section(header: str, lines: list[str], max_chars: int) -> str:
    text = header + "\n" + "\n".join(lines) if lines else header
    return _truncate(text, max_chars)


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        text = str(value).strip()
        return text or None
    return None


def format_session_context(session_context: object) -> str:
    if not isinstance(session_context, dict):
        return ""
    lines: list[str] = []
    for keys, label in _SESSION_CONTEXT_FIELDS:
        rendered: str | None = None
        for key in keys:
            rendered = _scalar_text(session_context.get(key))
            if rendered is not None:
                break
        if rendered is None:
            continue
        lines.append(f"- {label}: {_truncate(rendered, 500)}")
    if not lines:
        return ""
    return _capped_section("Session:", lines, MAX_SESSION_CONTEXT_SECTION_CHARS)


def parse_posthog_entity_refs(text: str) -> str:
    if not text.strip():
        return ""

    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    recording_ids: set[str] = set()

    def add(kind: str, raw: str) -> None:
        value = unquote(raw).strip().rstrip("/")
        if not value or value.lower() in _SKIP_PATH_SEGMENTS:
            return
        key = (kind, value)
        if key in seen:
            return
        seen.add(key)
        found.append(key)

    for match in _FEATURE_FLAG_PATH.finditer(text):
        add("feature_flag", match.group(1))
    for match in _INSIGHT_PATH.finditer(text):
        add("insight", match.group(1))
    for match in _RECORDING_PATH.finditer(text):
        add("recording", match.group(1))
        recording_ids.add(match.group(1).lower())
    for match in _DASHBOARD_PATH.finditer(text):
        add("dashboard", match.group(1))
    for match in _UUID_RE.finditer(text):
        value = match.group(0)
        if value.lower() in recording_ids:
            continue
        add("uuid", value)

    if not found:
        return ""
    lines = [f"- {_ENTITY_KIND_LABELS[kind]}: {value}" for kind, value in found]
    return _capped_section("Referenced PostHog entities:", lines, MAX_ENTITY_REFS_SECTION_CHARS)


def format_prior_tickets(tickets: Iterable[PriorTicket]) -> str:
    lines: list[str] = []
    for ticket in tickets:
        lines.append(f"- {ticket.title}")
        if ticket.reply:
            lines.append(f"  Final reply: {_truncate(ticket.reply, MAX_PRIOR_TICKET_REPLY_CHARS)}")
    if not lines:
        return ""
    return _capped_section("Previous resolved tickets:", lines, MAX_PRIOR_TICKETS_SECTION_CHARS)


def _prior_ticket_title(ticket: Ticket) -> str:
    # email_subject is the ticket title. last_message_text is often the customer's
    # last message and can carry email addresses, so it stays out of this section.
    subject = (ticket.email_subject or "").strip()
    if subject:
        return f"#{ticket.ticket_number}: {_truncate(subject, MAX_PRIOR_TICKET_TITLE_CHARS)}"
    return f"#{ticket.ticket_number}"


def _comment_team_ids(team: Team) -> set[int]:
    # Comments are RootTeamMixin, so save() stores them on the parent. Tickets stay on the environment.
    team_ids = {team.id}
    if team.parent_team_id:
        team_ids.add(team.parent_team_id)
    return team_ids


def _load_last_public_human_replies(team: Team, ticket_ids: list[str]) -> dict[str, str]:
    if not ticket_ids:
        return {}
    comments = (
        public_human_ticket_replies(_comment_team_ids(team), ticket_ids)
        .order_by("item_id", "-created_at", "-id")
        .distinct("item_id")
        .only("item_id", "content")
    )
    latest: dict[str, str] = {}
    for comment in comments:
        content = (comment.content or "").strip()
        if content and comment.item_id:
            latest[comment.item_id] = content
    return latest


def org_identity_is_attested(ticket: Ticket) -> bool:
    """Whether ``organization_id`` may key another account's content into this reply.

    ``organization_id`` is enrichment. It resolves from person properties and event ``$groups``,
    both client-supplied, so a widget visitor can claim any organization group key that already
    exists in the project. Naming the wrong account on an event is a mis-attribution; putting that
    account's prior replies and account properties in front of the reply model is a disclosure. Two
    sources clear that bar: an account the team itself mapped to a Slack channel, and a requester
    the host application vouched for through identity verification.
    """
    if ticket.organization_id_source == OrganizationIdSource.SLACK_CHANNEL_ACCOUNT:
        return True
    return ticket.identity_verified is True


def _restricted_prior_ticket_ids(team_id: int) -> list[UUID]:
    """Tickets that a rule keeps from some member of the team.

    Only object-level rules matter here. A resource-level one holds the reader back from the
    ticket being answered too, so it already bounds who reads the note; a rule on one ticket
    does not, and that is the ticket whose title and reply would otherwise leak into a note
    its reader was not allowed to open.
    """
    ids: list[UUID] = []
    for value in object_ids_restricted_from_any_member(team_id=team_id, resource="ticket", required_level="viewer"):
        try:
            ids.append(UUID(value))
        except ValueError:
            # resource_id is free-form, and a value that is not a ticket id matches no ticket.
            continue
    return ids


def load_prior_tickets(ticket: Ticket) -> list[PriorTicket]:
    identity = Q()
    if ticket.distinct_id:
        identity |= Q(distinct_id=ticket.distinct_id)
    if ticket.organization_id and org_identity_is_attested(ticket):
        identity |= Q(organization_id=ticket.organization_id)
    if not identity:
        return []

    team = ticket.team
    has_public_human_reply = public_human_ticket_replies(_comment_team_ids(team)).filter(
        item_id=Cast(OuterRef("id"), output_field=CharField()),
    )
    rows = list(
        Ticket.objects.filter(team_id=ticket.team_id, status=TicketStatus.RESOLVED)
        .filter(identity)
        .exclude(pk=ticket.pk)
        # Before the limit, so a ticket nobody may read does not take one of the few slots.
        .exclude(pk__in=_restricted_prior_ticket_ids(ticket.team_id))
        .filter(Exists(has_public_human_reply))
        .order_by("-created_at")[:MAX_PRIOR_TICKETS]
    )
    replies = _load_last_public_human_replies(team, [str(row.id) for row in rows])
    prior: list[PriorTicket] = []
    for row in rows:
        reply = replies.get(str(row.id))
        if not reply:
            continue
        prior.append(
            PriorTicket(
                ticket_number=row.ticket_number,
                title=_prior_ticket_title(row),
                reply=reply,
            )
        )
    return prior


def parse_account_property_ids(raw: object) -> list[str]:
    """Keep well-formed UUID strings, ordered, unique, capped. Invalid items are skipped."""
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        try:
            parsed = str(UUID(item))
        except ValueError:
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        ids.append(parsed)
        if len(ids) >= MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS:
            break
    return ids


def selected_account_property_ids(team: Team) -> list[str]:
    settings = team.conversations_settings or {}
    return parse_account_property_ids(settings.get("ai_context_account_property_ids"))


def format_account_property_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text:
        return None
    return _truncate(text, MAX_ACCOUNT_PROPERTY_VALUE_CHARS)


def format_account_properties(pairs: Iterable[tuple[str, object]]) -> str:
    lines: list[str] = []
    for name, value in pairs:
        rendered = format_account_property_value(value)
        if rendered is None:
            continue
        lines.append(f"- {name}: {rendered}")
        if len(lines) >= MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS:
            break
    if not lines:
        return ""
    return _capped_section("Account properties:", lines, MAX_ACCOUNT_SECTION_CHARS)


def _default_subject_access_control(team: Team) -> SubjectAccessControl | None:
    """The access the team's default rules give every member, with no member or role of their own.

    Reading a definition name needs somebody to read as, and the reply run has no request user.
    A subject with no member and no role resolves default rules only, and it drops the org-admin
    bypass, so the answer no longer changes with which membership row the database returns first.

    Definition names still resolve under it, because names are not object-scoped. Only workflow
    references are, and this path does not read them.
    """
    membership = (
        OrganizationMembership.objects.filter(organization_id=team.organization_id, user__is_active=True)
        .select_related("user")
        .first()
    )
    if membership is None:
        return None
    return SubjectAccessControl(membership.user, team=team, org_membership=membership)


def load_account_context(team: Team, organization_id: str | None) -> str:
    selected = selected_account_property_ids(team)
    if not selected or not organization_id:
        return ""
    try:
        # The account and value reads below are team-scoped only, and what they render goes into a
        # note that every agent who can open the ticket reads. There is no one reader to authorize
        # here, so the section needs the whole team to hold account access. A team that limited
        # Customer analytics to some of its members keeps that limit instead of losing it here.
        if not every_member_has_resource_access(team_id=team.id, resource="account", required_level="viewer"):
            return ""
        uac = _default_subject_access_control(team)
        if uac is None:
            return ""
        account = get_account(team.id, external_id=organization_id)
        if account is None:
            return ""
        # The same question one object down. The check above asks whether the team withheld
        # Customer analytics from anybody; this one asks whether it withheld this account.
        if str(account.id) in object_ids_restricted_from_any_member(
            team_id=team.id, resource="account", required_level="viewer"
        ):
            return ""
        values = list_active_custom_property_values(team.id, account.id)
        value_by_definition = {str(row.definition_id): row.value for row in values}
        pairs: list[tuple[str, object]] = []
        for definition_id in selected:
            if definition_id not in value_by_definition:
                continue
            view = get_custom_property_definition(team.id, definition_id, user_access_control=uac)
            if view is None or view.target_type != ACCOUNT_TARGET_TYPE or not view.name:
                continue
            pairs.append((view.name, value_by_definition[definition_id]))
        return format_account_properties(pairs)
    except Exception:
        capture_exception()
        return ""


def extra_ticket_context(ticket: Ticket, messages: list[Comment], team: Team) -> str:
    parts: list[str] = []
    prior = format_prior_tickets(load_prior_tickets(ticket))
    if prior:
        parts.append(prior)

    settings = team.conversations_settings or {}
    raw_docs = settings.get("docs_source") if isinstance(settings, dict) else None
    docs_source = raw_docs if isinstance(raw_docs, str) else None
    if is_posthog_docs_source(docs_source):
        chunks = [ticket.email_subject or "", *[message.content or "" for message in messages]]
        entities = parse_posthog_entity_refs("\n".join(chunks))
        if entities:
            parts.append(entities)

    account = load_account_context(team, ticket.organization_id if org_identity_is_attested(ticket) else None)
    if account:
        parts.append(account)
    return "\n\n".join(parts)
