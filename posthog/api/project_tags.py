"""Tagging for projects: the `tags` field, the list filter, and the analytics around both.

The pieces live here rather than in `project.py` so that module keeps to project settings.
`project.py` is the only caller.
"""

from typing import Any

from django.db.models import Prefetch, QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import exceptions, serializers

from posthog.event_usage import report_user_action
from posthog.models.project import Project
from posthog.models.tag import tagify
from posthog.models.tagged_item import TaggedItem
from posthog.models.user import User

TAGS_HELP_TEXT = (
    "Labels applied to this project. Names are trimmed and lowercased, and sending this field "
    "replaces the project's existing tags."
)

MATCH_MODES = ("all", "any")

# "all" adds one join per tag, so an unbounded list would hand Postgres a query plan that grows
# with whatever a caller puts in the query string.
MAX_TAGS_PER_FILTER = 20

# Query parameters for the project list, declared so they reach the generated clients.
LIST_FILTER_PARAMETERS = [
    OpenApiParameter(
        name="tags",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        description=(
            "Comma-separated tag names to filter by, for example `production,eu-region`. "
            f"Names are trimmed and lowercased before matching. At most {MAX_TAGS_PER_FILTER} "
            "distinct tags per request."
        ),
    ),
    OpenApiParameter(
        name="tags_match",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        enum=list(MATCH_MODES),
        description=(
            "How to combine the `tags` filter. `all` (the default) returns projects carrying "
            "every listed tag; `any` returns projects carrying at least one."
        ),
    ),
]


def tags_field() -> serializers.ListField:
    """The writable `tags` field shared by the project detail and list serializers."""
    return serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        help_text=TAGS_HELP_TEXT,
    )


def prefetch() -> Prefetch:
    """Load each project's tags in one query, under the attribute the serializers read."""
    return Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")


def current_names(project: Project) -> set[str]:
    """The project's tag names, preferring the prefetch the viewset attaches."""
    if hasattr(project, "prefetched_tags"):
        return {tagged_item.tag.name for tagged_item in project.prefetched_tags}
    return set(project.tagged_items.values_list("tag__name", flat=True))


def _parse_filter(query_params: Any) -> tuple[list[str], str] | None:
    """Read the `tags` / `tags_match` query pair, or None when no tag filter was asked for."""
    raw = query_params.get("tags")
    if not raw:
        return None
    tags = sorted({tagify(tag) for tag in raw.split(",") if tag.strip()})
    if not tags:
        return None
    if len(tags) > MAX_TAGS_PER_FILTER:
        raise exceptions.ValidationError({"tags": f"Filter by at most {MAX_TAGS_PER_FILTER} tags at a time."})
    match = query_params.get("tags_match", "all")
    if match not in MATCH_MODES:
        raise exceptions.ValidationError({"tags_match": f"Must be one of: {', '.join(MATCH_MODES)}."})
    return tags, match


def filter_queryset(queryset: QuerySet[Project], query_params: Any) -> QuerySet[Project]:
    """Narrow projects to those carrying every requested tag, or any of them under `tags_match=any`."""
    parsed = _parse_filter(query_params)
    if parsed is None:
        return queryset
    tags, match = parsed
    if match == "any":
        return queryset.filter(tagged_items__tag__name__in=tags).distinct()
    for tag in tags:
        queryset = queryset.filter(tagged_items__tag__name=tag)
    return queryset


def report_change(*, user: User, project: Project, tags_before: set[str], tags_after: set[str]) -> None:
    """Record a tag edit so adoption and depth of use can be measured after release."""
    added = tags_after - tags_before
    removed = tags_before - tags_after
    if not added and not removed:
        return
    report_user_action(
        user,
        "project tags updated",
        {
            "tags_count_before": len(tags_before),
            "tags_count_after": len(tags_after),
            "tags_added_count": len(added),
            "tags_removed_count": len(removed),
            "is_first_tagging": not tags_before and bool(tags_after),
            "all_tags_removed": bool(tags_before) and not tags_after,
            "organization_project_count": Project.objects.filter(organization_id=project.organization_id).count(),
        },
        team=project.passthrough_team,
    )
