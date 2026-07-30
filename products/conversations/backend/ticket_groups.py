# Ticket groups for the tickets list: ordered, tag-based groups derived from
# ticket tags. Group order IS the priority order (index 0 = highest). A ticket
# takes the highest-priority group with a matching tag; tickets matching no
# group rank with the first group (they still need routing).
#
# Teams define their own groups via conversations_settings.ticket_groups
# (an ordered [{label, tags}] list, validated by validate_ticket_groups
# from both the team and project serializers). Response-target ladders are
# one example use — the default below is only a starter example demonstrating
# the mechanic; every team's real groups (tag vocabulary, tiers, priorities)
# are their own. It MUST stay in lockstep with the frontend copy in
# products/conversations/frontend/scenes/tickets/ticketGroups.ts.
from typing import Any

from django.db.models import Case, Exists, IntegerField, OuterRef, Value, When

from rest_framework import serializers

from posthog.models.tagged_item import TaggedItem
from posthog.models.team import Team

# rank order; tag matching is exact (no prefixes)
DEFAULT_TICKET_GROUPS: list[dict[str, Any]] = [
    {"label": "Triage", "tags": ["needs_triage"]},  # 0 (also the unmatched fallback)
    {"label": "Urgent", "tags": ["urgent"]},  # 1
    {"label": "VIP", "tags": ["vip"]},  # 2
]


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
            and isinstance(group.get("tags"), list)
            and all(isinstance(tag, str) for tag in group["tags"])
            for group in groups
        )
        # Duplicate labels would collide in the frontend's per-label grouping
        # (headers key on the label), and a tag in two groups would rank with
        # its FIRST group in SQL while the frontend's tag→rank map keeps the
        # LAST — treat both as malformed too.
        and len({group["label"] for group in groups}) == len(groups)
        and len({tag for group in groups for tag in group["tags"]}) == sum(len(group["tags"]) for group in groups)
    ):
        return groups
    return DEFAULT_TICKET_GROUPS


def validate_ticket_groups(groups: Any) -> list[dict[str, Any]] | None:
    """Validate and normalize a conversations_settings.ticket_groups
    write: an ordered [{label, tags}] list of groups, or null to use the default.
    Called from the team and project serializers' conversations_settings
    validators. Rejects rather than coerces — the value is hand-edited in
    settings, and a silently dropped group would reorder the support queue.
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
    seen_tags: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise serializers.ValidationError({"ticket_groups": "Each group must be an object with a label and tags."})
        label = group.get("label")
        if not isinstance(label, str) or not label.strip():
            raise serializers.ValidationError({"ticket_groups": "Each group needs a non-empty label."})
        label = label.strip()
        if len(label) > 100:
            raise serializers.ValidationError({"ticket_groups": f"Label too long (max 100 characters): {label[:40]}…"})
        if label in seen_labels:
            raise serializers.ValidationError({"ticket_groups": f"Duplicate group label: {label}"})
        seen_labels.add(label)
        tags = group.get("tags")
        if not isinstance(tags, list):
            raise serializers.ValidationError(
                {"ticket_groups": f"Tags for “{label}” must be a list (it may be empty)."}
            )
        if len(tags) > 100:
            # Every tag becomes a parameter of the sort's per-group EXISTS
            # clause — an unbounded list would let one config bloat every
            # tickets-list query.
            raise serializers.ValidationError(
                {"ticket_groups": f"At most 100 tags per group (“{label}” has {len(tags)})."}
            )
        cleaned_tags: list[str] = []
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip():
                raise serializers.ValidationError({"ticket_groups": f"Tags for “{label}” must be non-empty strings."})
            tag = tag.strip()
            if len(tag) > 200:
                raise serializers.ValidationError({"ticket_groups": f"Tag too long (max 200 characters): {tag[:40]}…"})
            if tag in cleaned_tags:
                continue  # duplicate within the group — harmless, drop it
            if tag in seen_tags:
                # A tag in two groups would rank differently in SQL (first
                # group wins) than in any naive reading of the config.
                raise serializers.ValidationError({"ticket_groups": f"Tag “{tag}” appears in more than one group."})
            seen_tags.add(tag)
            cleaned_tags.append(tag)
        cleaned_groups.append({"label": label, "tags": cleaned_tags})
    return cleaned_groups


def ticket_group_rank_annotation(groups: list[dict[str, Any]]) -> Case | Value:
    """A per-ticket group rank for ORDER BY: the first
    (highest-priority) group with a matching tag wins, courtesy of Case
    evaluating Whens in order. Unmatched tickets take the default rank 0.

    Perf note: this is one correlated EXISTS per group (max 50 per the write
    validation). Each is served by TaggedItem's ticket-leading index
    (posthog_taggeditem_ticket_id_idx, migration 1033) with the tag-name
    filter applied to the handful of rows a ticket carries.
    """
    whens = [
        When(
            Exists(TaggedItem.objects.filter(ticket=OuterRef("pk"), tag__name__in=group["tags"])),
            then=Value(rank),
        )
        for rank, group in enumerate(groups)
        if group["tags"]
    ]
    if not whens:
        # Every configured group is tag-less (valid config) — CASE needs at
        # least one WHEN, so rank everything 0 directly.
        return Value(0, output_field=IntegerField())
    return Case(*whens, default=Value(0), output_field=IntegerField())
