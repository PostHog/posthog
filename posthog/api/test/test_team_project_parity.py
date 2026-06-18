import re

from posthog.test.base import BaseTest

from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from rest_framework import viewsets

from posthog.api.project import ProjectBackwardCompatSerializer, ProjectViewSet
from posthog.api.shared import ProjectBackwardCompatBasicSerializer, TeamBasicSerializer
from posthog.api.team import TeamSerializer, TeamViewSet

# /api/projects/ (Project model) is the canonical surface; /api/environments/ (Team model) is the
# backward-compat alias we intend to deprecate and permanently redirect onto /api/projects/. For that
# redirect to be safe, the project surface must be a SUPERSET of the environment surface — at two levels:
#   - RESOURCE parity: every serializer field and viewset action on the root Team viewset also exists on
#     the root Project viewset (the superset tests below).
#   - ROUTE parity: every URL reachable under /api/environments/ also resolves under /api/projects/. This is
#     broader than the root viewset pair — it covers nested viewsets registered directly on
#     `environments_router`, raw path()/include() mounts in urls.py, and resources that never opted into the
#     dual-route helper. test_environment_only_routes_match_known_allowlist walks the resolved URL trees to
#     catch those (the resource tests are blind to anything outside the root viewset pair).
#
# These allowlists capture the only intentional differences. Anything outside them is drift — most likely a
# field, action, or route added to the Team/environment side without mirroring it onto projects — and fails
# loudly so it gets fixed before it reaches clients.

# Fields that legitimately exist only on the project surface (a genuine Project concept, not a Team field).
# is_pending_deletion was added project-side on master; a project-only field is fine for the redirect target.
PROJECT_ONLY_SERIALIZER_FIELDS = {"product_description", "is_pending_deletion"}

# Actions that legitimately exist only on the project surface (operate on the Project, not the Team).
PROJECT_ONLY_ACTIONS = {"change_organization"}

# Routes (normalized suffix after `/api/<prefix>/<id>/`, path params -> `{id}`) that legitimately resolve
# ONLY under /api/environments/ and must NOT be mirrored onto projects:
#   - the customerio webhook is posted to a fixed env URL by a third party; redirecting it would break it,
#   - the async-query progress endpoints are internal, keyed by the team that ran the query.
# Anything else env-only is drift — mirror it onto /api/projects/ (dual-route the viewset) instead.
KNOWN_ENVIRONMENT_ONLY_ROUTES: set[str] = {
    "messaging/customerio/webhook",
    "progress",
    "query/{id}/progress",
}


def _serializer_field_names(serializer_class) -> set[str]:
    return set(serializer_class().fields.keys())


def _extra_action_names(viewset_class: type[viewsets.GenericViewSet]) -> set[str]:
    return {action.__name__ for action in viewset_class.get_extra_actions()}


_NAMED_GROUP = re.compile(r"\(\?P<[^>]+>(?:[^()]|\([^()]*\))*\)")  # (?P<x>...) incl. one nested ()
_PATH_CONVERTER = re.compile(r"<(?:[a-zA-Z_]+:)?[^>]+>")  # <int:x>, <drf_format_suffix:format>, <x>


def _route_segment(pattern) -> str:
    # str() of a regex pattern carries a leading ^ anchor; strip per-segment so concatenation is clean.
    return str(pattern.pattern).lstrip("^")


def _walk_routes(patterns, prefix=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _walk_routes(entry.url_patterns, prefix + _route_segment(entry))
        elif isinstance(entry, URLPattern):
            yield prefix + _route_segment(entry)


def _normalize_route(full: str, marker: str) -> str | None:
    if marker not in full:
        return None
    suffix = full[full.find(marker) + len(marker) :]
    suffix = _NAMED_GROUP.sub("{id}", suffix)  # (?P<x>...) -> {id}
    suffix = _PATH_CONVERTER.sub("{id}", suffix)  # <int:x> / <drf_format_suffix:format> -> {id}
    suffix = suffix.replace("\\", "")  # drop escapes: \. -> .
    suffix = re.sub(r"\.\{id\}", "", suffix)  # drop the DRF `.{format}` suffix variant
    for token in ("(?:", "(", ")", "?", "^", "$"):  # nuke leftover regex grouping syntax
        suffix = suffix.replace(token, "")
    suffix = re.sub(r"^\{id\}/?", "", suffix)  # drop the leading team/project id segment
    suffix = re.sub(r"/+", "/", suffix).strip("/")
    return suffix or None


def _routes_under(marker: str) -> set[str]:
    routes: set[str] = set()
    for full in _walk_routes(get_resolver().url_patterns):
        norm = _normalize_route(full, marker)
        if norm is not None:
            routes.add(norm)
    return routes


class TestTeamProjectParity(BaseTest):
    def test_detail_serializer_is_a_superset_of_team_serializer(self):
        team_fields = _serializer_field_names(TeamSerializer)
        project_fields = _serializer_field_names(ProjectBackwardCompatSerializer)

        missing_on_project = team_fields - project_fields
        self.assertEqual(
            missing_on_project,
            set(),
            f"/api/environments/ exposes fields that /api/projects/ does not: {sorted(missing_on_project)}. "
            f"Mirror them onto ProjectBackwardCompatSerializer (or the redirect to /api/projects/ would drop them).",
        )

        project_only = project_fields - team_fields
        self.assertEqual(
            project_only,
            PROJECT_ONLY_SERIALIZER_FIELDS,
            f"Unexpected project-only serializer fields: {sorted(project_only - PROJECT_ONLY_SERIALIZER_FIELDS)}. "
            f"If intentional, add them to PROJECT_ONLY_SERIALIZER_FIELDS.",
        )

    def test_list_serializers_are_identical(self):
        team_basic_fields = _serializer_field_names(TeamBasicSerializer)
        project_basic_fields = _serializer_field_names(ProjectBackwardCompatBasicSerializer)
        self.assertEqual(
            team_basic_fields,
            project_basic_fields,
            "List responses diverge between /api/environments/ and /api/projects/. "
            f"Only on environments: {sorted(team_basic_fields - project_basic_fields)}; "
            f"only on projects: {sorted(project_basic_fields - team_basic_fields)}.",
        )

    def test_viewset_actions_are_a_superset_of_team_viewset(self):
        team_actions = _extra_action_names(TeamViewSet)
        project_actions = _extra_action_names(ProjectViewSet)

        missing_on_project = team_actions - project_actions
        self.assertEqual(
            missing_on_project,
            set(),
            f"/api/environments/ exposes actions that /api/projects/ does not: {sorted(missing_on_project)}. "
            f"Mirror them onto ProjectViewSet (or the redirect to /api/projects/ would 404 them).",
        )

        project_only = project_actions - team_actions
        self.assertEqual(
            project_only,
            PROJECT_ONLY_ACTIONS,
            f"Unexpected project-only actions: {sorted(project_only - PROJECT_ONLY_ACTIONS)}. "
            f"If intentional, add them to PROJECT_ONLY_ACTIONS.",
        )

    def test_shared_actions_expose_the_same_http_methods(self):
        # For every action present on both viewsets, the allowed HTTP verbs must match — a GET-only action
        # on one side and GET+PATCH on the other would silently drop writes after the redirect.
        team_actions = {a.__name__: a for a in TeamViewSet.get_extra_actions()}
        project_actions = {a.__name__: a for a in ProjectViewSet.get_extra_actions()}

        mismatches: dict[str, tuple] = {}
        for name in team_actions.keys() & project_actions.keys():
            team_methods = {m.lower() for m in getattr(team_actions[name], "mapping", {})}
            project_methods = {m.lower() for m in getattr(project_actions[name], "mapping", {})}
            if team_methods != project_methods:
                mismatches[name] = (sorted(team_methods), sorted(project_methods))

        self.assertEqual(
            mismatches, {}, f"Shared actions expose different HTTP methods (team vs project): {mismatches}"
        )

    def test_environment_only_routes_match_known_allowlist(self):
        # Route-level (URL-tree) parity: walk both prefixes' resolved patterns and assert the only routes
        # reachable solely under /api/environments/ are the known, intentionally environment-only ones.
        env_only = _routes_under("api/environments/") - _routes_under("api/projects/")

        unexpected = env_only - KNOWN_ENVIRONMENT_ONLY_ROUTES
        self.assertEqual(
            unexpected,
            set(),
            "New route(s) reachable only under /api/environments/ with no /api/projects/ counterpart: "
            f"{sorted(unexpected)}. A redirect from /api/environments/ to /api/projects/ would not reach them. "
            "Either mirror the route onto /api/projects/ (dual-route the viewset, or register it project-side) "
            "or, if it is intentionally environment-scoped, add it to KNOWN_ENVIRONMENT_ONLY_ROUTES with a reason.",
        )

        resolved = KNOWN_ENVIRONMENT_ONLY_ROUTES - env_only
        self.assertEqual(
            resolved,
            set(),
            "Route(s) in KNOWN_ENVIRONMENT_ONLY_ROUTES now have a /api/projects/ counterpart (or no longer "
            f"exist): {sorted(resolved)}. Remove them from the allowlist so it reflects only still-env-only routes.",
        )
