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
#    "operator": "is_set" | "is_not_set"}  — no value field
#   {"type": "ticket_property", "key": "created_at",
#    "operator": "date_before" | "date_after", "value": "-3d" or ISO datetime}
#       — see the shared date grammar below; relative values resolve at query
#       time in the team's timezone
#
# ## The shared created_at date grammar
#
# Both sides accept EXACTLY the same values (validated at write time here):
#   - Relative: `-N<unit>` with unit in {h, d, w, m, y} (hour/day/week/month/
#     year), N an integer 1..1000, and an optional case-sensitive `Start` or
#     `End` suffix — e.g. "-3d", "-12h", "-1mStart", "-1yEnd". FULLMATCH only:
#     no "+3d", "3d", "-3days", "3d ago", "-3dstart".
#   - ISO datetime: zero-padded `YYYY-MM-DD`, optionally followed by a time
#     (`T` or space separator, `HH:MM[:SS[.ffffff]]`) and a `Z`/`±HH:MM`
#     offset — anything the ISO regex below matches AND
#     datetime.fromisoformat parses.
#
# Resolution semantics (identical on both sides):
#   - bare `-Nu` is a ROLLING window: now minus N units, time-of-day kept;
#   - `Start`/`End`: subtract N units, then snap to the start/end of the unit
#     (weeks start on Sunday, matching dayjs's default en locale);
#   - naive ISO values take the resolving timezone; offsets are respected.
# The one accepted divergence: the backend resolves in the TEAM timezone,
# the frontend in the BROWSER timezone (documented in ticketGroups.ts).
#
# Response-target ladders are one example use — the default below is only a
# starter example demonstrating the mechanic; every team's real groups are
# their own. This module MUST stay in lockstep with the frontend copy in
# products/conversations/frontend/scenes/tickets/ticketGroups.ts.
import re
import calendar
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When

from dateutil.relativedelta import relativedelta
from rest_framework import serializers

from posthog.models.tagged_item import TaggedItem
from posthog.models.team import Team

from products.conversations.backend.models.constants import Channel, Priority, Status

# rank order; tag matching is exact (no prefixes)
DEFAULT_TICKET_GROUPS: list[dict[str, Any]] = [
    # 0 (also the unmatched fallback)
    {"label": "Triage", "filters": [{"type": "ticket_tags", "operator": "any_of", "value": ["needs_triage"]}]},
    {"label": "Urgent", "filters": [{"type": "ticket_tags", "operator": "any_of", "value": ["urgent"]}]},  # 1
    {"label": "VIP", "filters": [{"type": "ticket_tags", "operator": "any_of", "value": ["vip"]}]},  # 2
]

# Enum-valued ticket properties filterable with "in" — mirrors the model's
# TextChoices so new channels/statuses/priorities are accepted automatically.
_PROPERTY_IN_VALUES: dict[str, frozenset[str]] = {
    "channel_source": frozenset(Channel.values),
    "status": frozenset(Status.values),
    "priority": frozenset(Priority.values),
}

# The full ticket_property vocabulary: valid operators per key.
_PROPERTY_OPERATORS: dict[str, frozenset[str]] = {
    "channel_source": frozenset({"in"}),
    "status": frozenset({"in"}),
    "priority": frozenset({"in"}),
    "email_from": frozenset({"icontains"}),
    "sla_due_at": frozenset({"is_set", "is_not_set"}),
    "created_at": frozenset({"date_before", "date_after"}),
}


# The shared created_at date grammar (see the module docstring) — these two
# regexes are duplicated verbatim in ticketGroups.ts.
_RELATIVE_DATE_REGEX = re.compile(r"-(?P<number>[1-9][0-9]*)(?P<unit>[hdwmy])(?P<position>Start|End)?")
_ISO_DATE_REGEX = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?")
# Keeps resolution well inside datetime's year range (1000y from now is fine).
_MAX_RELATIVE_NUMBER = 1000
_RELATIVE_DELTA_KWARGS = {"h": "hours", "d": "days", "w": "weeks", "m": "months", "y": "years"}


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
        resolved = anchor - relativedelta(**{_RELATIVE_DELTA_KWARGS[unit]: number})
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


def _validate_filter(filter_config: Any, label: str) -> dict[str, Any]:
    """Validate and normalize one group filter; returns the cleaned filter."""
    if not isinstance(filter_config, dict):
        raise serializers.ValidationError({"ticket_groups": f"Each filter in “{label}” must be an object with a type."})
    filter_type = filter_config.get("type")
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
                "ticket_groups": f'Unknown filter type in “{label}”: {filter_type!r} (use "ticket_tags" or "ticket_property").'
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


def validate_ticket_groups(groups: Any) -> list[dict[str, Any]] | None:
    """Validate and normalize a conversations_settings.ticket_groups
    write: an ordered [{label, filters}] list of groups, or null to use the
    default. Called from the team and project serializers'
    conversations_settings validators. Rejects rather than coerces — the value
    is hand-edited in settings, and a silently dropped group or filter would
    reorder the support queue.
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
            {"label": label, "filters": [_validate_filter(filter_config, label) for filter_config in filters]}
        )
    return cleaned_groups


def _filter_condition(filter_config: dict[str, Any], timezone_info: ZoneInfo) -> Q:
    """One filter's SQL condition, for ANDing into the group's WHEN."""
    if filter_config["type"] == "ticket_tags":
        return Q(Exists(TaggedItem.objects.filter(ticket=OuterRef("pk"), tag__name__in=filter_config["value"])))
    key = filter_config["key"]
    operator = filter_config["operator"]
    if operator == "in":
        return Q(**{f"{key}__in": filter_config["value"]})
    if operator == "icontains":
        return Q(**{f"{key}__icontains": filter_config["value"]})
    if operator == "is_set":
        return Q(**{f"{key}__isnull": False})
    if operator == "is_not_set":
        return Q(**{f"{key}__isnull": True})
    # date_before / date_after — relative values resolve once per query build
    resolved = _resolve_date_value(filter_config["value"], timezone_info)
    if resolved is None:
        # Outside the shared grammar (a config written past the validator) —
        # the filter matches nothing, same as the frontend.
        return Q(pk__in=[])
    lookup = "lt" if operator == "date_before" else "gt"
    return Q(**{f"{key}__{lookup}": resolved})


def ticket_group_rank_annotation(groups: list[dict[str, Any]], timezone_info: ZoneInfo | None = None) -> Case | Value:
    """A per-ticket group rank for ORDER BY: the first (highest-priority)
    group whose filters ALL match wins, courtesy of Case evaluating Whens in
    order. Groups with no filters emit no When (they match nothing).
    Unmatched tickets take the default rank 0.

    Relative date values ("-3d") resolve here, at query-build time, in
    timezone_info — pass the team's timezone (tickets.py does); defaults
    to UTC.

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
            condition &= _filter_condition(filter_config, timezone_info)
        whens.append(When(condition, then=Value(rank)))
    if not whens:
        # Every configured group is filter-less (valid config) — CASE needs at
        # least one WHEN, so rank everything 0 directly.
        return Value(0, output_field=IntegerField())
    return Case(*whens, default=Value(0), output_field=IntegerField())
