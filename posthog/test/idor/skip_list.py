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
}
