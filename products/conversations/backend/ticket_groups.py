# Ticket groups for the tickets list: ordered, filter-based groups. Group
# order IS the priority order (index 0 = highest). A ticket takes the FIRST
# group whose filters ALL match (AND within a group, first-match-wins across
# groups); tickets matching no group rank with the first group (they still
# need routing). A group with no filters matches nothing (a placeholder while
# configuring).
#
# Teams define their own groups via conversations_settings.ticket_groups
# (an ordered [{label, filters}] list, validated by validate_ticket_groups
# from both the team and project serializers). Each filter is one of:
#   {"type": "ticket_tags", "operator": "any_of", "value": ["vip", ...]}
#       — the ticket has ANY of these tags (exact names)
#   {"type": "ticket_property", "key": "channel_source"|"status"|"priority",
#    "operator": "in", "value": [...]}
#   {"type": "ticket_property", "key": "email_from", "operator": "icontains",
#    "value": "@bigcorp.com"}  — case-insensitive substring
#   {"type": "ticket_property", "key": "sla_due_at",
#    "operator": "is_set" | "is_not_set"}  — no value field. Whether the ticket
#       has a deadline AT ALL, which is not the same question as whether it has
#       been missed — for that use sla_state below.
#   {"type": "ticket_property", "key": "sla_state", "operator": "in",
#    "value": ["breached", "at-risk", "on-track"]}  — the same states the list's
#       SLA filter uses (backend/sla.py). All three require a deadline to exist,
#       so a ticket with none is in none of them.
#   {"type": "ticket_property", "key": "created_at",
#    "operator": "date_before" | "date_after", "value": "-3d" or ISO datetime}
#       — see the shared date grammar below; relative values resolve at query
#       time in the team's timezone
#   {"type": "sql", "expression": "message_count > 5 AND priority = 'high'"}
#       — a HogQL boolean expression, compiled to Postgres by
#       ticket_group_sql.py. The escape hatch for conditions this vocabulary
#       doesn't cover; tags are NOT reachable from it (AND a ticket_tags filter
#       alongside instead).
#
# ## The created_at date grammar
#
# Accepted values (validated at write time here; the settings editor
# pre-checks the same grammar in ticketGroups.ts's
# isValidTicketGroupDateValue, but this side is authoritative):
#   - Relative: `-N<unit>` with unit in {h, d, w, m, y} (hour/day/week/month/
#     year), N an integer 1..1000, and an optional case-sensitive `Start` or
#     `End` suffix — e.g. "-3d", "-12h", "-1mStart", "-1yEnd". FULLMATCH only:
#     no "+3d", "3d", "-3days", "3d ago", "-3dstart".
#   - ISO datetime: zero-padded `YYYY-MM-DD`, optionally followed by a time
#     (`T` or space separator, `HH:MM[:SS[.ffffff]]`) and a `Z`/`±HH:MM`
#     offset — anything the ISO regex below matches AND
#     datetime.fromisoformat parses.
#
# Resolution semantics:
#   - bare `-Nu` is a ROLLING window: now minus N units, time-of-day kept;
#   - `Start`/`End`: subtract N units, then snap to the start/end of the unit
#     (weeks start on Sunday, matching dayjs's default en locale);
#   - naive ISO values take the resolving timezone; offsets are respected.
# Resolution happens here, at query-build time, in the TEAM's timezone.
#
# ## Group membership is computed here and only here
#
# The rank this module computes is serialized onto every listed ticket
# (`ticket_group_rank`), and the frontend labels its column and section
# headers from it. There is deliberately NO client-side evaluator to keep in
# step: a `sql` filter is a HogQL expression, which a browser can't evaluate.
#
# Response-target ladders are one example use — the default below is only a
# starter example demonstrating the mechanic; every team's real groups are
# their own.
import re
import calendar
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import BooleanField, Case, Exists, IntegerField, OuterRef, Q, Value, When
from django.db.models.expressions import RawSQL
from django.utils import timezone

from dateutil.relativedelta import relativedelta
from rest_framework import serializers

from posthog.exceptions_capture import capture_exception
from posthog.models.tagged_item import TaggedItem
from posthog.models.team import Team

from products.conversations.backend.models.constants import Channel, Priority, Status
from products.conversations.backend.sla import SLA_STATES, sla_state_condition
from products.conversations.backend.ticket_group_sql import (
    TicketGroupSqlError,
    build_ticket_group_sql_database,
    compile_ticket_group_sql,
)

# rank order; tag matching is exact (no prefixes)
DEFAULT_TICKET_GROUPS: list[dict[str, Any]] = [
    # 0 (also the unmatched fallback)
    {"label": "Triage", "filters": [{"type": "ticket_tags", "operator": "any_of", "value": ["needs_triage"]}]},
    {"label": "Urgent", "filters": [{"type": "ticket_tags", "operator": "any_of", "value": ["urgent"]}]},  # 1
    {"label": "VIP", "filters": [{"type": "ticket_tags", "operator": "any_of", "value": ["vip"]}]},  # 2
]

# SQL expression filters are the escape hatch, not the main vocabulary, and each
# one costs a Postgres round trip to validate on save.
MAX_SQL_FILTERS = 5

# Enum-valued ticket properties filterable with "in" — mirrors the model's
# TextChoices so new channels/statuses/priorities are accepted automatically.
_PROPERTY_IN_VALUES: dict[str, frozenset[str]] = {
    "channel_source": frozenset(Channel.values),
    "status": frozenset(Status.values),
    "priority": frozenset(Priority.values),
    "sla_state": frozenset(SLA_STATES),
}

# The full ticket_property vocabulary: valid operators per key.
_PROPERTY_OPERATORS: dict[str, frozenset[str]] = {
    "channel_source": frozenset({"in"}),
    "status": frozenset({"in"}),
    "priority": frozenset({"in"}),
    "email_from": frozenset({"icontains"}),
    "sla_due_at": frozenset({"is_set", "is_not_set"}),
    "sla_state": frozenset({"in"}),
    "created_at": frozenset({"date_before", "date_after"}),
}


# The shared created_at date grammar (see the module docstring) — these two
# regexes are duplicated verbatim in ticketGroups.ts.
_RELATIVE_DATE_REGEX = re.compile(r"-(?P<number>[1-9][0-9]*)(?P<unit>[hdwmy])(?P<position>Start|End)?")
_ISO_DATE_REGEX = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?")
# Keeps resolution well inside datetime's year range (1000y from now is fine).
_MAX_RELATIVE_NUMBER = 1000
_RELATIVE_DELTAS: dict[str, Callable[[int], relativedelta]] = {
    "h": lambda n: relativedelta(hours=n),
    "d": lambda n: relativedelta(days=n),
    "w": lambda n: relativedelta(weeks=n),
    "m": lambda n: relativedelta(months=n),
    "y": lambda n: relativedelta(years=n),
}


def _start_of(value: datetime, unit: str) -> datetime:
    if unit == "h":
        return value.replace(minute=0, second=0, microsecond=0)
    if unit == "w":  # weeks start on Sunday, matching dayjs's default en locale
        value = value - timedelta(days=(value.weekday() + 1) % 7)
    elif unit == "m":
        value = value.replace(day=1)
    elif unit == "y":
        value = value.replace(month=1, day=1)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of(value: datetime, unit: str) -> datetime:
    if unit == "h":
        return value.replace(minute=59, second=59, microsecond=999999)
    if unit == "w":
        value = value + timedelta(days=6 - (value.weekday() + 1) % 7)
    elif unit == "m":
        value = value.replace(day=calendar.monthrange(value.year, value.month)[1])
    elif unit == "y":
        value = value.replace(month=12, day=31)
    return value.replace(hour=23, minute=59, second=59, microsecond=999999)


def _parse_iso_date_value(value: str, timezone_info: ZoneInfo) -> datetime | None:
    """The ISO half of the shared grammar: the regex constrains the shape
    (fromisoformat alone is looser — it also takes basic forms like
    "20260716" that dayjs reads differently), fromisoformat validates the
    calendar. Naive values take timezone_info."""
    if not _ISO_DATE_REGEX.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone_info)
    return parsed.astimezone(timezone_info)


def _resolve_date_value(value: str, timezone_info: ZoneInfo, now: datetime | None = None) -> datetime | None:
    """Resolve a created_at filter value per the shared grammar, in
    timezone_info. Returns None for anything outside the grammar — the write
    validator rejects those, but the settings blob has other writers, so
    callers treat None as "matches nothing" (frontend parity: resolveDateValue
    returns null)."""
    match = _RELATIVE_DATE_REGEX.fullmatch(value)
    if match:
        number = int(match.group("number"))
        if number > _MAX_RELATIVE_NUMBER:
            return None
        unit = match.group("unit")
        anchor = (now or datetime.now(tz=timezone_info)).astimezone(timezone_info)
        resolved = anchor - _RELATIVE_DELTAS[unit](number)
        if match.group("position") == "Start":
            return _start_of(resolved, unit)
        if match.group("position") == "End":
            return _end_of(resolved, unit)
        return resolved
    return _parse_iso_date_value(value, timezone_info)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_structurally_usable_filter(filter_config: Any) -> bool:
    """Enough shape to build SQL from without erroring — the write validator
    is stricter (enum membership, lengths, non-empty lists, date parseability),
    but the read side only needs to not 500."""
    if not isinstance(filter_config, dict):
        return False
    if filter_config.get("type") == "ticket_tags":
        return filter_config.get("operator") == "any_of" and _is_string_list(filter_config.get("value"))
    if filter_config.get("type") == "sql":
        expression = filter_config.get("expression")
        # Compilability is the write validator's business; a stored expression
        # that no longer compiles matches nothing rather than 500ing the list.
        return isinstance(expression, str) and bool(expression.strip())
    if filter_config.get("type") == "ticket_property":
        key = filter_config.get("key")
        operator = filter_config.get("operator")
        if not isinstance(key, str) or operator not in _PROPERTY_OPERATORS.get(key, frozenset()):
            return False
        if operator == "in":
            return _is_string_list(filter_config.get("value"))
        if operator in ("is_set", "is_not_set"):
            return True  # no value needed
        # icontains / date_before / date_after — only the type matters; a
        # garbage date string resolves to None and the filter matches nothing
        return isinstance(filter_config.get("value"), str)
    return False


def team_ticket_groups(team: Team) -> list[dict[str, Any]]:
    """The team's configured groups, or the default. TeamSerializer validates
    writes, but the JSONField is shared with other writers — treat a malformed
    value as unset rather than 500ing the tickets list."""
    settings = team.conversations_settings or {}
    groups = settings.get("ticket_groups")
    if (
        isinstance(groups, list)
        and len(groups) > 0
        and all(
            isinstance(group, dict)
            and isinstance(group.get("label"), str)
            and isinstance(group.get("filters"), list)
            and all(_is_structurally_usable_filter(filter_config) for filter_config in group["filters"])
            for group in groups
        )
        # Duplicate labels would collide in the frontend's per-label grouping
        # (headers key on the label) — treat those as malformed too.
        and len({group["label"] for group in groups}) == len(groups)
    ):
        return groups
    return DEFAULT_TICKET_GROUPS


def _validate_string_list_value(filter_config: dict[str, Any], label: str, what: str) -> list[str]:
    """A filter's non-empty list-of-non-empty-strings value, trimmed and deduped."""
    value = filter_config.get("value")
    if not isinstance(value, list) or not value:
        raise serializers.ValidationError({"ticket_groups": f"{what} in “{label}” needs a non-empty list of values."})
    if len(value) > 100:
        # Every entry becomes a parameter of the sort's per-group clause — an
        # unbounded list would let one config bloat every tickets-list query.
        raise serializers.ValidationError(
            {"ticket_groups": f"At most 100 values per filter ({what} in “{label}” has {len(value)})."}
        )
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise serializers.ValidationError({"ticket_groups": f"{what} in “{label}” must be non-empty strings."})
        item = item.strip()
        if len(item) > 200:
            raise serializers.ValidationError({"ticket_groups": f"Value too long (max 200 characters): {item[:40]}…"})
        if item not in cleaned:  # duplicate within the filter — harmless, drop it
            cleaned.append(item)
    return cleaned


def _validate_sql_filter(
    filter_config: dict[str, Any], label: str, sql_database: Any, team_id: int | None
) -> dict[str, Any]:
    """Validate a `sql` filter by actually compiling it, so a bad expression is
    rejected in the settings editor rather than breaking the tickets list."""
    expression = filter_config.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise serializers.ValidationError(
            {"ticket_groups": f"The SQL expression filter in “{label}” needs a non-empty expression."}
        )
    expression = expression.strip()
    if sql_database is None or team_id is None:
        # No team to compile against — the project is being created, so there's
        # no schema to resolve the expression yet. Refuse rather than store an
        # expression nobody has checked.
        raise serializers.ValidationError(
            {
                "ticket_groups": (
                    f"The SQL expression filter in “{label}” can only be added to an existing project — "
                    "create the project first, then add it in Settings → Support → Ticket groups."
                )
            }
        )
    try:
        compile_ticket_group_sql(expression, sql_database, team_id)
    except TicketGroupSqlError as error:
        raise serializers.ValidationError({"ticket_groups": f"SQL expression in “{label}”: {error}"})
    return {"type": "sql", "expression": expression}


def _validate_filter(
    filter_config: Any, label: str, sql_database: Any = None, team_id: int | None = None
) -> dict[str, Any]:
    """Validate and normalize one group filter; returns the cleaned filter."""
    if not isinstance(filter_config, dict):
        raise serializers.ValidationError({"ticket_groups": f"Each filter in “{label}” must be an object with a type."})
    filter_type = filter_config.get("type")
    if filter_type == "sql":
        return _validate_sql_filter(filter_config, label, sql_database, team_id)
    if filter_type == "ticket_tags":
        operator = filter_config.get("operator")
        if operator != "any_of":
            raise serializers.ValidationError(
                {"ticket_groups": f'Unknown operator for ticket_tags in “{label}”: {operator!r} (use "any_of").'}
            )
        return {
            "type": "ticket_tags",
            "operator": "any_of",
            "value": _validate_string_list_value(filter_config, label, "Tags"),
        }
    if filter_type != "ticket_property":
        raise serializers.ValidationError(
            {
                "ticket_groups": f'Unknown filter type in “{label}”: {filter_type!r} (use "ticket_tags", "ticket_property" or "sql").'
            }
        )
    key = filter_config.get("key")
    if not isinstance(key, str) or key not in _PROPERTY_OPERATORS:
        valid_keys = ", ".join(sorted(_PROPERTY_OPERATORS))
        raise serializers.ValidationError(
            {"ticket_groups": f"Unknown ticket property in “{label}”: {key!r} (valid keys: {valid_keys})."}
        )
    operator = filter_config.get("operator")
    if operator not in _PROPERTY_OPERATORS[key]:
        valid_operators = ", ".join(sorted(_PROPERTY_OPERATORS[key]))
        raise serializers.ValidationError(
            {
                "ticket_groups": f"Operator {operator!r} is not valid for “{key}” in “{label}” (valid: {valid_operators})."
            }
        )
    if operator == "in":
        values = _validate_string_list_value(filter_config, label, f"Values for “{key}”")
        allowed = _PROPERTY_IN_VALUES[key]
        for item in values:
            if item not in allowed:
                raise serializers.ValidationError(
                    {
                        "ticket_groups": f"Unknown value for “{key}” in “{label}”: “{item}” (valid: {', '.join(sorted(allowed))})."
                    }
                )
        return {"type": "ticket_property", "key": key, "operator": "in", "value": values}
    if operator == "icontains":
        value = filter_config.get("value")
        if not isinstance(value, str) or not value.strip():
            raise serializers.ValidationError(
                {"ticket_groups": f"The “{key}” filter in “{label}” needs a non-empty string value."}
            )
        value = value.strip()
        if len(value) > 200:
            raise serializers.ValidationError({"ticket_groups": f"Value too long (max 200 characters): {value[:40]}…"})
        return {"type": "ticket_property", "key": key, "operator": "icontains", "value": value}
    if operator in ("is_set", "is_not_set"):
        if "value" in filter_config:
            raise serializers.ValidationError(
                {"ticket_groups": f"The “{operator}” operator in “{label}” takes no value."}
            )
        return {"type": "ticket_property", "key": key, "operator": operator}
    # date_before / date_after
    value = filter_config.get("value")
    if not isinstance(value, str) or not value.strip():
        raise serializers.ValidationError(
            {
                "ticket_groups": f'The “{operator}” filter in “{label}” needs a relative date (e.g. "-3d") or ISO datetime string.'
            }
        )
    value = value.strip()
    # The strict shared grammar (see the module docstring) — the frontend
    # resolves the same values with the same semantics, so anything looser
    # would sort one way on the server and label another way in the client.
    relative_match = _RELATIVE_DATE_REGEX.fullmatch(value)
    if relative_match:
        if int(relative_match.group("number")) > _MAX_RELATIVE_NUMBER:
            raise serializers.ValidationError(
                {
                    "ticket_groups": f"Relative dates in “{label}” can go back at most {_MAX_RELATIVE_NUMBER} units (“{value}”)."
                }
            )
    elif _parse_iso_date_value(value, ZoneInfo("UTC")) is None:
        raise serializers.ValidationError(
            {
                "ticket_groups": f'Can\'t parse the date “{value}” in “{label}” — use a relative date like "-3d" (units h/d/w/m/y, optional Start/End suffix) or an ISO datetime like "2026-07-01".'
            }
        )
    return {"type": "ticket_property", "key": key, "operator": operator, "value": value}


def groups_use_sql(groups: Any) -> bool:
    """Whether any group uses a `sql` filter — the gate for building the HogQL
    database, which is far too expensive to do on every tickets list.

    Runs on unvalidated input (the write path calls it before the per-group shape
    checks), so every level is type-checked: a non-list `filters` must not raise
    here, or a malformed write would 500 instead of getting its 400.
    """
    if not isinstance(groups, list):
        return False
    return any(
        isinstance(filter_config, dict) and filter_config.get("type") == "sql"
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("filters"), list)
        for filter_config in group["filters"]
    )


def validate_ticket_groups(groups: Any, team: Team | None = None, user: Any = None) -> list[dict[str, Any]] | None:
    """Validate and normalize a conversations_settings.ticket_groups
    write: an ordered [{label, filters}] list of groups, or null to use the
    default. Called from the team and project serializers'
    conversations_settings validators. Rejects rather than coerces — the value
    is hand-edited in settings, and a silently dropped group or filter would
    reorder the support queue.

    `team`/`user` are only needed to compile `sql` filters (see
    ticket_group_sql.py); pass the team being edited and the requesting user.
    """
    if groups is None:
        return None
    if not isinstance(groups, list):
        raise serializers.ValidationError({"ticket_groups": "Must be a list of groups or null for the default."})
    if not groups:
        raise serializers.ValidationError(
            {"ticket_groups": "Must contain at least one group, or be null for the default."}
        )
    if len(groups) > 50:
        raise serializers.ValidationError({"ticket_groups": "At most 50 groups are allowed."})
    # Each `sql` filter costs a Postgres planning round trip to validate, and the
    # group/filter caps alone would allow 500 of them per save. They're an escape
    # hatch for what the declarative filters can't express, so a handful is
    # plenty — and this bounds the work one settings save can ask for.
    sql_filter_count = sum(
        1
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("filters"), list)
        for filter_config in group["filters"]
        if isinstance(filter_config, dict) and filter_config.get("type") == "sql"
    )
    if sql_filter_count > MAX_SQL_FILTERS:
        raise serializers.ValidationError(
            {
                "ticket_groups": (
                    f"At most {MAX_SQL_FILTERS} SQL expression filters are allowed ({sql_filter_count} given)."
                )
            }
        )
    # Only pay for the HogQL database when an expression actually needs compiling.
    sql_database = build_ticket_group_sql_database(team, user) if team is not None and groups_use_sql(groups) else None
    team_id = team.pk if team is not None else None
    cleaned_groups: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise serializers.ValidationError(
                {"ticket_groups": "Each group must be an object with a label and filters."}
            )
        label = group.get("label")
        if not isinstance(label, str) or not label.strip():
            raise serializers.ValidationError({"ticket_groups": "Each group needs a non-empty label."})
        label = label.strip()
        if len(label) > 100:
            raise serializers.ValidationError({"ticket_groups": f"Label too long (max 100 characters): {label[:40]}…"})
        if label in seen_labels:
            raise serializers.ValidationError({"ticket_groups": f"Duplicate group label: {label}"})
        seen_labels.add(label)
        filters = group.get("filters")
        if not isinstance(filters, list):
            raise serializers.ValidationError(
                {"ticket_groups": f"Filters for “{label}” must be a list (it may be empty)."}
            )
        if len(filters) > 10:
            raise serializers.ValidationError(
                {"ticket_groups": f"At most 10 filters per group (“{label}” has {len(filters)})."}
            )
        cleaned_groups.append(
            {
                "label": label,
                "filters": [_validate_filter(filter_config, label, sql_database, team_id) for filter_config in filters],
            }
        )
    return cleaned_groups


# (key, operator) -> a Q builder with the ORM lookup written literally, so no
# config value is ever interpolated into a lookup path (defense in depth on
# top of the write validator and _is_structurally_usable_filter, and it keeps
# static analysis honest about ORM field injection).
def _sla_state_condition(states: Any) -> Q:
    """Any-of over the shared SLA states (backend/sla.py). `now` is read here, at
    query-build time, so one query ranks every ticket against one instant."""
    now = timezone.now()
    condition = Q()
    for state in states:
        condition |= sla_state_condition(state, now)
    return condition


_PROPERTY_CONDITIONS: dict[tuple[str, str], Callable[[Any], Q]] = {
    ("channel_source", "in"): lambda value: Q(channel_source__in=value),
    ("status", "in"): lambda value: Q(status__in=value),
    ("priority", "in"): lambda value: Q(priority__in=value),
    ("sla_state", "in"): _sla_state_condition,
    ("email_from", "icontains"): lambda value: Q(email_from__icontains=value),
    ("sla_due_at", "is_set"): lambda _value: Q(sla_due_at__isnull=False),
    ("sla_due_at", "is_not_set"): lambda _value: Q(sla_due_at__isnull=True),
    ("created_at", "date_before"): lambda resolved: Q(created_at__lt=resolved),
    ("created_at", "date_after"): lambda resolved: Q(created_at__gt=resolved),
}


def _filter_condition(
    filter_config: dict[str, Any],
    timezone_info: ZoneInfo,
    sql_database: Any = None,
    team_id: int | None = None,
) -> Q:
    """One filter's SQL condition, for ANDing into the group's WHEN."""
    if filter_config["type"] == "ticket_tags":
        return Q(Exists(TaggedItem.objects.filter(ticket=OuterRef("pk"), tag__name__in=filter_config["value"])))
    if filter_config["type"] == "sql":
        if sql_database is None or team_id is None:
            # No compile context — match nothing rather than mis-rank.
            return Q(pk__in=[])
        try:
            # verify_executable=False: the write validator already planned this
            # against Postgres, and a round trip per filter per request isn't
            # affordable on the list path. list() catches the runtime failures
            # that leaves possible and degrades instead of 500ing.
            sql, params = compile_ticket_group_sql(
                filter_config["expression"], sql_database, team_id, verify_executable=False
            )
        except TicketGroupSqlError:
            # Validated at write time, so reaching here means the config predates
            # a validation change or the ticket schema moved under it. Match
            # nothing (consistent with the other unusable-filter paths) and
            # report it rather than failing every tickets list.
            capture_exception()
            return Q(pk__in=[])
        return Q(RawSQL(sql, params, output_field=BooleanField()))
    key = filter_config["key"]
    operator = filter_config["operator"]
    condition = _PROPERTY_CONDITIONS.get((key, operator))
    if condition is None:
        # Unknown combo written past the validator — match nothing, like the frontend.
        return Q(pk__in=[])
    if operator in ("date_before", "date_after"):
        # Relative values resolve once per query build.
        resolved = _resolve_date_value(filter_config["value"], timezone_info)
        if resolved is None:
            # Outside the shared grammar — the filter matches nothing, same as the frontend.
            return Q(pk__in=[])
        return condition(resolved)
    return condition(filter_config.get("value"))


def ticket_group_rank_annotation(
    groups: list[dict[str, Any]],
    timezone_info: ZoneInfo | None = None,
    sql_database: Any = None,
    team_id: int | None = None,
) -> Case | Value:
    """A per-ticket group rank for ORDER BY: the first (highest-priority)
    group whose filters ALL match wins, courtesy of Case evaluating Whens in
    order. Groups with no filters emit no When (they match nothing).
    Unmatched tickets take the default rank 0.

    Relative date values ("-3d") resolve here, at query-build time, in
    timezone_info — pass the team's timezone (tickets.py does); defaults
    to UTC.

    `sql_database`/`team_id` are only needed when a group uses a `sql` filter
    (gate on groups_use_sql before paying to build the database). Without them
    such a filter matches nothing.

    Perf note: each ticket_tags filter is one correlated EXISTS (max 50
    groups × 10 filters per the write validation). Each is served by
    TaggedItem's ticket-leading index (posthog_taggeditem_ticket_id_idx,
    migration 1033) with the tag-name filter applied to the handful of rows
    a ticket carries; the ticket_property filters hit the ticket row itself.
    """
    timezone_info = timezone_info or ZoneInfo("UTC")
    whens = []
    for rank, group in enumerate(groups):
        if not group["filters"]:
            continue
        condition = Q()
        for filter_config in group["filters"]:
            condition &= _filter_condition(filter_config, timezone_info, sql_database, team_id)
        whens.append(When(condition, then=Value(rank)))
    if not whens:
        # Every configured group is filter-less (valid config) — CASE needs at
        # least one WHEN, so rank everything 0 directly.
        return Value(0, output_field=IntegerField())
    return Case(*whens, default=Value(0), output_field=IntegerField())
