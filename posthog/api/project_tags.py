"""Tagging for projects: the `tags` field, the list filter, and the analytics around both.

The pieces live here rather than in `project.py` so that module keeps to project settings.
`project.py` is the only caller.
"""

from typing import Any

from django.db.models import Prefetch, QuerySet

from rest_framework import serializers

from posthog.api.tagged_item import filter_queryset_by_tags, tags_filter_parameters
from posthog.event_usage import report_user_action
from posthog.models.project import Project
from posthog.models.tagged_item import TaggedItem
from posthog.models.user import User

TAGS_HELP_TEXT = (
    "Labels applied to this project. Names are trimmed and lowercased, and sending this field "
    "replaces the project's existing tags."
)

# Query parameters for the project list, declared so they reach the generated clients.
LIST_FILTER_PARAMETERS = tags_filter_parameters(example="production,eu-region")


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


def filter_queryset(queryset: QuerySet[Project], query_params: Any) -> QuerySet[Project]:
    """Narrow projects to those carrying every requested tag, or any of them under `tags_match=any`."""
    return filter_queryset_by_tags(queryset, query_params)


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
