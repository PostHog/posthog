"""
Explicit skip list for auto-IDOR tests.

Every entry is a viewset *name* (not the class itself, so this file can be
imported without triggering Django app loading) mapped to a documented
reason. The CI coverage check (Phase 3) treats skip_list entries as
"intentionally uncovered" so they don't show up as coverage gaps.

Categories of valid skips:

  - AUTO_URL_MISMATCH — viewset uses a non-pk lookup field or expects a
    non-UUID/integer id; auto-URL construction can't produce a valid
    URL. These are NOT IDOR bugs — they just can't be exercised by the
    generic test.

  - LATENT_ERROR_HANDLING_BUG — viewset returns 500 on cross-team access
    because it doesn't catch Model.DoesNotExist. Queryset scoping is
    correct (no data leak); separate bugfix required.

  - INTENTIONAL_CROSS_TEAM — viewset is meant to be shared/public.

If you're skipping a new viewset, pick a category and add a brief note
of what's going on. Unexplained skips fail CI.
"""

from __future__ import annotations

# Keys: viewset class name as discovered by `discover_idor_test_cases`.
# Values: (category, explanation)
IDOR_TEST_SKIP_LIST: dict[str, tuple[str, str]] = {
    "ColumnConfigurationViewSet": (
        "LATENT_ERROR_HANDLING_BUG",
        "safely_get_object at posthog/api/column_configuration.py:65 uses "
        "queryset.get(pk=pk) which raises DoesNotExist instead of Http404. "
        "Queryset is correctly team-scoped (no IDOR), but cross-team access "
        "returns 500 instead of 404. Fix: use get_object_or_404.",
    ),
    "EventDefinitionViewSet": (
        "LATENT_ERROR_HANDLING_BUG",
        "dangerously_get_object at posthog/api/event_definition.py:346 uses "
        "EventDefinition.objects.get(id=..., team__project_id=...) which raises "
        "DoesNotExist instead of Http404. Queryset is correctly team-scoped "
        "(no IDOR), but cross-team access returns 500 instead of 404. "
        "Fix: wrap in try/except or use get_object_or_404.",
    ),
    "AppMetricsViewSet": (
        "RETURNS_200_WITH_EMPTY_AGGREGATION",
        "retrieve() at posthog/api/app_metrics.py:27 is an aggregation endpoint. "
        "The ClickHouse query at AppMetricsQuery.query() is correctly team-scoped "
        "(filters by team_id = self.team.pk) so cross-team access returns an empty "
        "aggregation (200 OK with zero counts), not victim data. Not an IDOR, but "
        "the endpoint should return 404 when the PluginConfig/batch_export id "
        "doesn't belong to the caller's team.",
    ),
    "CoreEventViewSet": (
        "CUSTOM_MODEL_VALIDATION",
        "CoreEvent model enforces `Filter configuration is required` on save(), "
        "requiring complex filter setup this auto-factory can't provide. "
        "Add a dedicated fixture if needed.",
    ),
    "DataWarehouseModelPathViewSet": (
        "CUSTOM_FIELD_TYPE",
        "DataWarehouseModelPath uses a LabelTreeField for `path` that the "
        "minimal-instance factory doesn't know how to populate. Add a dedicated "
        "fixture if needed.",
    ),
    "ObjectMediaPreviewViewSet": (
        "MUTUALLY_EXCLUSIVE_CONSTRAINTS",
        "ObjectMediaPreview has a DB constraint requiring exactly one of "
        "`uploaded_media` or `exported_asset` to be set, plus a similar one on "
        "`object` fields. Auto-factory can't satisfy mutually-exclusive "
        "constraints without domain knowledge. Add a dedicated fixture if needed.",
    ),
    "MaterializedColumnSlotViewSet": (
        "COMPLEX_DEPENDENCIES",
        "MaterializedColumnSlot requires a PropertyDefinition FK; the column "
        "materialization machinery involves ClickHouse state that's painful to "
        "set up in a unit test. Add a dedicated fixture if needed.",
    ),
    "SessionRecordingExternalReferenceViewSet": (
        "LATENT_FILTER_REWRITE_BUG",
        "Viewset is mounted under /api/environments/{team_id}/... but its model "
        "SessionRecordingExternalReference has no team_id column (team is "
        "derived via session_recording.team). _filter_queryset_by_parents_lookups "
        "crashes with 'Cannot resolve keyword team_id into field' on any detail "
        "call. Fix: add `filter_rewrite_rules = {'team_id': 'session_recording__team_id'}` "
        "to the viewset at posthog/session_recordings/session_recording_external_reference_api.py:213.",
    ),
}
