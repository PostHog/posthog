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
    "AppMetricsViewSet": (
        "RETURNS_200_WITH_EMPTY_AGGREGATION",
        "retrieve() at posthog/api/app_metrics.py:27 is an aggregation endpoint. "
        "The ClickHouse query at AppMetricsQuery.query() is correctly team-scoped "
        "(filters by team_id = self.team.pk) so cross-team access returns an empty "
        "aggregation (200 OK with zero counts), not victim data. Not an IDOR, but "
        "the endpoint should return 404 when the PluginConfig/batch_export id "
        "doesn't belong to the caller's team.",
    ),
    # -------------------------------------------------------------------
    # Legacy flat viewsets registered without a /projects|environments/
    # prefix. They dispatch through `param_derived_from_user_current_team`
    # which pins the queryset to request.user.current_team — IDOR testing
    # via URL substitution isn't applicable. They're all slated for removal.
    # -------------------------------------------------------------------
    "LegacyCohortViewSet": ("LEGACY_FLAT_URL", "Unnested /api/cohort/ route; pinned to request.user.current_team."),
    "LegacyDashboardsViewSet": (
        "LEGACY_FLAT_URL",
        "Unnested /api/dashboard/ route (comment: 'Should be completely unused now'); slated for removal.",
    ),
    "LegacyElementViewSet": ("LEGACY_FLAT_URL", "Unnested /api/element/ route; pinned to request.user.current_team."),
    "LegacyEnterprisePersonViewSet": (
        "LEGACY_FLAT_URL",
        "Unnested /api/person/ route; pinned to request.user.current_team.",
    ),
    "LegacyEventViewSet": ("LEGACY_FLAT_URL", "Unnested /api/event/ route; pinned to request.user.current_team."),
    "LegacyFeatureFlagViewSet": (
        "LEGACY_FLAT_URL",
        "Unnested /api/feature_flag/ (library-side flag evaluation); pinned to request.user.current_team.",
    ),
    "LegacyInsightViewSet": ("LEGACY_FLAT_URL", "Unnested /api/dashboard_item/ (renamed insight)."),
    "LegacyPluginConfigViewSet": ("LEGACY_FLAT_URL", "Unnested /api/plugin_config/."),
    # -------------------------------------------------------------------
    # Custom lookup_field — URL value is not the model pk. These need
    # dedicated hand-written IDOR tests because URL substitution requires
    # domain knowledge of what the URL parameter means.
    # -------------------------------------------------------------------
    "OrganizationFeatureFlagView": (
        "CUSTOM_LOOKUP_FIELD",
        "lookup_field='feature_flag_key' — URL is FF key string, not a pk.",
    ),
    # -------------------------------------------------------------------
    # Viewsets that don't have an inferrable model (queryset=None and no
    # serializer_class.Meta.model). These are typically query/endpoint
    # wrappers (HogQL, MCP tools, debugger) that proxy ClickHouse queries
    # or external services — there's no model to IDOR.
    # -------------------------------------------------------------------
    "ErrorTrackingExternalReferenceViewSet": (
        "NO_MODEL",
        "No queryset.model; wraps Integration lookups. IDOR tested via Integration viewset.",
    ),
    "ErrorTrackingFingerprintViewSet": (
        "NO_MODEL",
        "No queryset.model; fingerprint merge action wrapper. Covered by ErrorTrackingIssueViewSet tests.",
    ),
    "EventViewSet": ("NO_MODEL", "No model; queries ClickHouse events table. team_id scoping is on the CH query."),
    "FixHogQLViewSet": ("NO_MODEL", "No model; HogQL query fixer action."),
    "HistoricalExportsAppMetricsViewSet": ("NO_MODEL", "No model; metrics aggregation endpoint."),
    "LegalDocumentViewSet": ("NO_MODEL", "No queryset.model; legal documents are org-scoped org-admin only."),
    "QueryViewSet": ("NO_MODEL", "No model; HogQL query execution endpoint (team_id scoping is in the query)."),
    "RepoViewSet": ("NO_MODEL", "No model; external repo integration."),
    "RunViewSet": ("NO_MODEL", "No model; temporal run lookup."),
    "SessionGroupSummaryViewSet": ("NO_MODEL", "No model; wraps LLM-summarization actions."),
}


# ---------------------------------------------------------------------------
# Phase 5a — viewsets to skip for the writable-FK PATCH test specifically.
#
# The base IDOR_TEST_SKIP_LIST already excludes viewsets that can't be
# auto-tested at all (legacy, no model, custom lookup_field). Many of those
# implicitly skip the FK test too — they don't even reach the discovery
# step. This list is for cases where the GET/PATCH cross-team test works
# fine but the FK-in-PATCH variant needs a separate exclusion (e.g., the
# viewset has no writable FK, or PATCH semantics deliberately permit a
# cross-tenant target).
#
# Categories:
#   - INTENTIONAL_CROSS_TENANT_FK — the FK is meant to span tenants
#     (rare; usually a system reference like a global plugin).
#   - NO_WRITABLE_TENANT_FK — discovery returns nothing actionable
#     (here only as documentation; entries listed here just fail loud
#     if discovery later starts surfacing something).
# ---------------------------------------------------------------------------
IDOR_FK_PATCH_SKIP_LIST: dict[str, tuple[str, str]] = {}


# ---------------------------------------------------------------------------
# Phase 5b — viewsets to skip for the writable-FK POST (CREATE) test.
#
# Unlike PATCH, CREATE has to synthesize a full valid request body.
# Some viewsets need explicit skips even when their PATCH variant works:
#   - POST disabled (read-only or detail-only viewsets)
#   - Body synthesis infeasible (custom validators we can't satisfy and
#     no body fixture is registered yet)
#   - POST kicks off external side effects (Temporal workflows, file
#     writes) we don't want exercising in the test path
#
# Categories:
#   - POST_NOT_ALLOWED — viewset's create action is disabled or 405s.
#   - BODY_SYNTHESIS_INFEASIBLE — serializer needs a custom body shape
#     that introspection can't build, no fixture registered.
#   - INTENTIONAL_CROSS_TENANT_FK — the FK is meant to span tenants.
#   - REQUIRES_FILESYSTEM_OR_TEMPORAL — POST triggers heavy side effects.
# ---------------------------------------------------------------------------
IDOR_FK_POST_SKIP_LIST: dict[str, tuple[str, str]] = {
    "EdgeViewSet": (
        "POST_NOT_ALLOWED",
        "EdgeSerializer marks `source_id`/`target_id` as read_only, so the default ModelViewSet "
        "create() can't satisfy Edge.source/target FK requirements and POST returns 500. Latent "
        "viewset bug unrelated to IDOR — Edges are created indirectly via the data modeling "
        "workflow, not via direct POST. Excluded from FK-in-POST sweep.",
    ),
}


# ---------------------------------------------------------------------------
# Phase 5c — viewsets to skip for the @action FK / name-pattern test.
#
# Action endpoints have varying semantics — some kick off Temporal workflows,
# some emit side effects to external services, some are detail-route (need
# attacker-owned resource), some take complex multi-FK bodies. When the
# parametric can't reasonably exercise an action without false noise,
# entries here suppress it loudly with a documented category.
#
# Categories:
#   - ACTION_NOT_TESTABLE — action shape we can't auto-build a body for
#     (e.g., needs uploaded files, multipart, or wraps a side-effect).
#   - INTENTIONAL_CROSS_TENANT — action is meant to span tenants
#     (very rare; document the threat model).
#   - BODY_SYNTHESIS_INFEASIBLE — request body can't be filled by
#     introspection and no fixture is registered yet.
#   - REQUIRES_FILESYSTEM_OR_TEMPORAL — action triggers heavy side
#     effects (Temporal workflow, file write, external API) that we
#     don't want exercising in the test path.
#
# Keys here are formatted "ViewSetName.action_method_name" so multiple
# actions on the same viewset can be skipped independently.
# ---------------------------------------------------------------------------
IDOR_ACTION_SKIP_LIST: dict[str, tuple[str, str]] = {}


# ---------------------------------------------------------------------------
# Known-latent 5xx responses.
#
# The cross-tenant tests previously called `skipTest()` whenever an endpoint
# returned 5xx, on the theory that the response was a server bug rather than
# an IDOR. That swallowed real signal: a 5xx after the request reached the
# victim's data is itself worth investigating. The tests now emit a warning
# (and still run a sentinel-leak check on the response body) for any 5xx
# that is not listed here.
#
# Add an entry only when a 5xx is **understood** and **safe** — typically
# a downstream dependency that's unavailable in the test env, or a known
# latent bug tracked elsewhere. Keys take the same shape as the action skip
# list ("ViewSetName.action_method_name") for actions, or just
# "ViewSetName" for the POST/PATCH parametrics.
# ---------------------------------------------------------------------------
IDOR_5XX_KNOWN_LATENT: dict[str, tuple[str, str]] = {}
