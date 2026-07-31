# The SLA states a ticket can be in, defined once.
#
# Two surfaces need the same answer and must not drift: the tickets list's `sla`
# query-param filter (api/tickets.py) and the `sla_state` ticket-group filter
# (ticket_groups.py). ticket_groups.py can't import from api/tickets.py — that
# module imports ticket_groups — so the shared definition lives here, below both.
#
# All three states require a deadline to exist. A ticket with no `sla_due_at` is
# in NONE of them, which is deliberate: "nobody promised this customer anything
# yet" is a different (and often more urgent) triage case than a deadline that's
# been missed. Match those with the `sla_due_at is_not_set` filter instead.
from datetime import datetime, timedelta

from django.db.models import Q

# How close to the deadline counts as at-risk rather than on-track.
AT_RISK_WINDOW = timedelta(hours=1)

SLA_STATE_BREACHED = "breached"
SLA_STATE_AT_RISK = "at-risk"
SLA_STATE_ON_TRACK = "on-track"
SLA_STATES = (SLA_STATE_BREACHED, SLA_STATE_AT_RISK, SLA_STATE_ON_TRACK)


def sla_state_condition(state: str, now: datetime) -> Q:
    """The ORM condition for one SLA state, as of `now`. Lookups are written
    literally (no interpolated field paths) so config values can never reach a
    lookup path. An unknown state matches nothing rather than everything."""
    if state == SLA_STATE_BREACHED:
        return Q(sla_due_at__lt=now)
    if state == SLA_STATE_AT_RISK:
        return Q(sla_due_at__gte=now, sla_due_at__lte=now + AT_RISK_WINDOW)
    if state == SLA_STATE_ON_TRACK:
        return Q(sla_due_at__gt=now + AT_RISK_WINDOW)
    return Q(pk__in=[])
