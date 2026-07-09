"""
Emit PostHog analytics events for ticket and message state changes.

These events power workflow triggers (e.g. "if ticket pending for X days, resolve it").
Staff/system actions use the actor's distinct_id; customer actions use the ticket's distinct_id.
Events are sent to the customer's PostHog project via their team's API token.
"""

from datetime import datetime
from typing import Literal

from django.utils import timezone

import structlog

from posthog.api.capture import capture_internal
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.event_usage import groups as build_groups
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.organization import OrganizationMembership
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.models.team import Team
from posthog.models.user import User
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.settings import SITE_URL

from products.conversations.backend.cache import get_cached_resolved_groups, set_cached_resolved_groups
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "conversations_events"

ActorType = Literal["user", "system", "external", "customer"]


def _get_actor_properties(actor: User | None, actor_type: ActorType) -> dict:
    """Build actor-related properties for an event."""
    return {
        "actor_type": actor_type,
        "actor_id": actor.id if actor else None,
        "actor_email": actor.email if actor else None,
    }


def _get_actor_distinct_id(
    ticket: Ticket,
    actor: User | None,
    actor_type: ActorType,
) -> str:
    """Determine the distinct_id based on who performed the action.

    User actions are attributed to the staff member.
    System/external/customer actions are attributed to the customer.
    """
    if actor_type == "user" and actor and actor.distinct_id:
        return actor.distinct_id
    return ticket.distinct_id or ticket.channel_source or "unknown"


# Channels whose customer email is tied to a provider-verified identity and is therefore safe
# to use for organization attribution.
_EMAIL_FALLBACK_CHANNELS = frozenset({Channel.EMAIL.value, Channel.SLACK.value, Channel.TEAMS.value})

# Latest organization/customer group keys from the customer's recent events. We read the
# dedicated $group_N columns (set on every event that carries $groups) rather than filtering on
# $groupidentify events: posthog.group(type, key) called without properties associates the group
# with all subsequent events but emits no $groupidentify (the documented SDK behavior), and even
# newer SDKs only re-emit it for newly-seen groups. A $groupidentify filter would therefore
# silently miss exactly the cross-region customers this fallback exists for — those whose apps
# don't pass group properties, or whose last group identify predates the 30-day window.
# {org_col}/{customer_select} are interpolated from this project's own group-type indexes (see
# _resolve_groups_from_analytics); column names can't be HogQL placeholders.
GROUPS_FROM_EVENTS_QUERY = """
SELECT
    argMax({org_col}, timestamp),
    {customer_select}
FROM events
WHERE distinct_id IN {{distinct_ids}}
  AND timestamp >= now() - INTERVAL 30 DAY
  AND {org_col} != ''
"""


def _resolve_groups_from_analytics(team: Team, distinct_ids: list[str]) -> dict | None:
    """Resolve ``$groups`` from the customer's recent analytics events in ClickHouse.

    Fallback for when the ``OrganizationMembership`` lookup misses: that join runs
    against this region's Postgres only, so accounts registered in another region
    (e.g. an EU user filing a ticket against a US project) are invisible to it.
    Their identified app sessions, however, stamp ``$group_N`` onto every event
    captured into this project, which is cross-region by construction.

    Event-supplied groups are captured with the project's public token and are
    therefore spoofable — fine for analytics enrichment (same trust level as
    ``$identify``), never for authorization. ``instance``/``project`` are rebuilt
    server-side so fallback-path events match ``build_groups()`` output.
    """
    if not distinct_ids:
        return None

    cached = get_cached_resolved_groups(team.id, distinct_ids)
    if cached is not None:
        return cached or None  # {} is the negative-cache sentinel

    # The $group_N column index is per-project, so resolve the org/customer indexes from this
    # project's group-type mapping. Doubles as a cheap guard: bail (and negative-cache) for
    # projects without an organization group type before touching ClickHouse.
    group_type_index = {
        gtm["group_type"]: gtm["group_type_index"] for gtm in get_group_types_for_project(team.project_id)
    }
    org_index = group_type_index.get("organization")
    if org_index is None:
        set_cached_resolved_groups(team.id, distinct_ids, None)
        return None
    customer_index = group_type_index.get("customer")

    # Indexes are trusted ints (0-4) from the project's own mapping; safe to interpolate.
    org_col = f"`$group_{org_index}`"
    customer_select = (
        f"argMaxIf(`$group_{customer_index}`, timestamp, `$group_{customer_index}` != '')"
        if customer_index is not None
        else "''"
    )
    query = GROUPS_FROM_EVENTS_QUERY.format(org_col=org_col, customer_select=customer_select)

    # Deferred: hogql.query pulls the whole query-runner layer, and this module loads
    # at django.setup() via the conversations signal wiring.
    from posthog.hogql import ast  # noqa: PLC0415
    from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415

    with tags_context(product=Product.CONVERSATIONS, feature=Feature.QUERY):
        response = execute_hogql_query(
            query,
            placeholders={"distinct_ids": ast.Constant(value=distinct_ids)},
            team=team,
            query_type="conversations_groups_lookup",
        )

    groups: dict | None = None
    if response.results:
        org_key, customer_key = response.results[0]
        if org_key:
            groups = {"instance": SITE_URL, "project": str(team.uuid), "organization": org_key}
            if customer_key:
                groups["customer"] = customer_key

    set_cached_resolved_groups(team.id, distinct_ids, groups)
    return groups


def _resolve_org_groups(ticket: Ticket, team: Team) -> tuple[bool, dict | None]:
    """Resolve the customer organization's ``$groups`` for a ticket.

    Returns ``(process_person, groups)``. ``groups`` is ``None`` when the
    customer can't be tied to a PostHog organization.

    The web widget sets ``ticket.distinct_id`` to a real PostHog distinct_id,
    so the membership is found directly. Other channels (Slack, Email, MS
    Teams) set ``distinct_id`` to the customer email (or empty), so we fall
    back to looking the person up by ``properties.email`` in ClickHouse and
    resolving the membership through that person's real distinct_ids.
    """
    # 1. Real distinct_id (web widget). An identified person is authoritative: if they
    # have no org membership, don't guess via email (a shared email could resolve to a
    # different person's org), so return early instead of falling through.
    if ticket.distinct_id:
        # Only is_identified is read, and the membership lookup below keys off the ticket's own
        # distinct_id — so skip fetching the person's distinct_ids.
        with personhog_caller_tag("conversations/ticket-event-person"):
            persons = get_persons_by_distinct_ids(team.id, [ticket.distinct_id], distinct_id_limit=0)
        if any(p.is_identified for p in persons):
            membership = (
                OrganizationMembership.objects.select_related("organization")
                .filter(user__distinct_id=ticket.distinct_id)
                .first()
            )
            if membership:
                return True, build_groups(membership.organization, team)
            # Membership rows are region-local: accounts registered in another region
            # never appear in this Postgres. Fall back to the $groups their sessions
            # stamped onto this project's analytics events (same distinct_id, so the
            # shared-email caveat above still holds).
            groups = _resolve_groups_from_analytics(team, [ticket.distinct_id])
            if groups:
                return True, groups
            return False, None

    # 2. Email fallback, restricted to channels with a provider-verified email identity.
    # Never trust the public widget's attacker-controlled anonymous_traits.email here.
    if ticket.channel_source not in _EMAIL_FALLBACK_CHANNELS:
        return False, None

    email = (ticket.anonymous_traits or {}).get("email") or ticket.email_from
    if email:
        # person_lookup pulls the HogQL query layer; this module loads at django.setup()
        # via the conversations signal wiring, so import it lazily.
        from products.conversations.backend.person_lookup import _get_persons_by_email  # noqa: PLC0415

        person = _get_persons_by_email(team, [email]).get(email.lower())
        if person is not None and person.distinct_ids:
            membership = (
                OrganizationMembership.objects.select_related("organization")
                .filter(user__distinct_id__in=person.distinct_ids)
                .first()
            )
            if membership:
                return True, build_groups(membership.organization, team)
            # Same cross-region fallback as above, keyed by the person's distinct_ids.
            groups = _resolve_groups_from_analytics(team, person.distinct_ids)
            if groups:
                return True, groups

    return False, None


def _groups_from_org_id(team: Team, organization_id: str) -> dict:
    """Rebuild minimal $groups from a stored org id, skipping the expensive resolver."""
    return {"instance": SITE_URL, "project": str(team.uuid), "organization": organization_id}


def _get_ticket_base_properties(ticket: Ticket) -> dict:
    return {
        "ticket_id": str(ticket.id),
        "ticket_number": ticket.ticket_number,
        "channel_source": ticket.channel_source,
        "channel_detail": ticket.channel_detail,
        "status": ticket.status,
        "priority": ticket.priority,
    }


def _get_customer_properties(ticket: Ticket, *, include_distinct_id: bool = False) -> dict:
    """Customer identity on the ticket, for workflow filters and analytics."""
    traits = ticket.anonymous_traits or {}
    properties = {
        "customer_name": traits.get("name", ""),
        "customer_email": traits.get("email") or ticket.email_from or "",
    }
    if include_distinct_id:
        properties["customer_distinct_id"] = ticket.distinct_id or ""
    return properties


def _get_sla_properties(ticket: Ticket, now: datetime) -> dict:
    """SLA state at the moment of the event.

    Stamped on events (rather than derived later) so attainment metrics reflect the
    deadline that was in force at the time, even if the SLA is reset afterwards.
    `sla_delta_seconds` is positive when past due, negative when time remains.
    """
    if ticket.sla_due_at is None:
        return {"sla_due_at": None, "sla_active": False, "sla_breached": False, "sla_delta_seconds": None}
    delta_seconds_float = (now - ticket.sla_due_at).total_seconds()
    return {
        "sla_due_at": ticket.sla_due_at.isoformat(),
        "sla_active": True,
        "sla_breached": delta_seconds_float > 0,
        "sla_delta_seconds": int(delta_seconds_float),
    }


def capture_ticket_created(ticket: Ticket) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties.update(_get_customer_properties(ticket))

    team = ticket.team
    team_id = team.id
    process_person = False
    try:
        process_person, groups = _resolve_org_groups(ticket, team)
        if groups is not None:
            properties["$groups"] = groups
            org_id = groups.get("organization")
            if org_id and not ticket.organization_id:
                Ticket.objects.filter(id=ticket.id).update(organization_id=org_id)
                ticket.organization_id = org_id
    except Exception:
        logger.exception("ticket_created_person_lookup_failed", team_id=team_id, ticket_id=str(ticket.id))

    capture_internal(
        token=team.api_token,
        event_name="$conversation_ticket_created",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
        properties=properties,
        process_person_profile=process_person,
    )


def capture_ticket_status_changed(
    ticket: Ticket,
    old_status: str,
    new_status: str,
    actor: User | None = None,
    actor_type: ActorType = "system",
) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["old_status"] = old_status
    properties["new_status"] = new_status
    properties.update(_get_actor_properties(actor, actor_type))
    properties.update(_get_customer_properties(ticket, include_distinct_id=True))

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_ticket_status_changed",
        event_source=EVENT_SOURCE,
        distinct_id=_get_actor_distinct_id(ticket, actor, actor_type),
        timestamp=None,
        properties=properties,
    )


def capture_ticket_priority_changed(
    ticket: Ticket,
    old_priority: str | None,
    new_priority: str | None,
    actor: User | None = None,
    actor_type: ActorType = "system",
) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["old_priority"] = old_priority
    properties["new_priority"] = new_priority
    properties.update(_get_actor_properties(actor, actor_type))
    properties.update(_get_customer_properties(ticket, include_distinct_id=True))

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_ticket_priority_changed",
        event_source=EVENT_SOURCE,
        distinct_id=_get_actor_distinct_id(ticket, actor, actor_type),
        timestamp=None,
        properties=properties,
    )


def capture_ticket_assigned(
    ticket: Ticket,
    assignee_type: str | None,
    assignee_id: str | None,
    actor: User | None = None,
    actor_type: ActorType = "system",
) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["assignee_type"] = assignee_type
    properties["assignee_id"] = assignee_id
    properties.update(_get_actor_properties(actor, actor_type))
    properties.update(_get_customer_properties(ticket, include_distinct_id=True))

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_ticket_assigned",
        event_source=EVENT_SOURCE,
        distinct_id=_get_actor_distinct_id(ticket, actor, actor_type),
        timestamp=None,
        properties=properties,
    )


def capture_message_sent(
    ticket: Ticket,
    message_id: str,
    message_content: str,
    author: User | None = None,
) -> None:
    """Team member sent a message on a ticket."""
    properties = _get_ticket_base_properties(ticket)
    properties["message_id"] = message_id
    properties["message_content"] = (message_content or "")[:1000]
    properties["author_type"] = "team"
    properties.update(_get_actor_properties(author, "user"))
    properties.update(_get_customer_properties(ticket, include_distinct_id=True))
    properties.update(_get_sla_properties(ticket, timezone.now()))

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_message_sent",
        event_source=EVENT_SOURCE,
        distinct_id=_get_actor_distinct_id(ticket, author, "user"),
        timestamp=None,
        properties=properties,
    )


def capture_message_received(ticket: Ticket, message_id: str, message_content: str) -> None:
    """Customer sent a message on a ticket."""
    properties = _get_ticket_base_properties(ticket)
    properties["message_id"] = message_id
    properties["message_content"] = (message_content or "")[:1000]
    properties["author_type"] = "customer"
    properties.update(_get_customer_properties(ticket))

    team = ticket.team
    process_person = False
    try:
        if ticket.organization_id:
            properties["$groups"] = _groups_from_org_id(team, ticket.organization_id)
            process_person = True
        else:
            process_person, groups = _resolve_org_groups(ticket, team)
            if groups is not None:
                properties["$groups"] = groups
    except Exception:
        logger.exception("message_received_person_lookup_failed", team_id=team.id, ticket_id=str(ticket.id))

    capture_internal(
        token=team.api_token,
        event_name="$conversation_message_received",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
        properties=properties,
        process_person_profile=process_person,
    )
