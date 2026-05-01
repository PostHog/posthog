"""Single-gate guest deflection middleware.

All guest enforcement runs through this middleware. The request either matches a rule in
`GUEST_RULES` that explicitly allows it, or the request is deflected — `404` for API paths
(so guest clients can't enumerate the surface area) or `redirect("/guest")` for non-API
SPA routes (so the FE scene allowlist/landing page can take over).

Since `is_guest=True` now flips the AC layer's default from allow to deny, the per-resource
rules below are just a thin adapter: they pull `team_id` and `resource_id` out of the URL
and ask `UserAccessControl.access_level_for_object` whether the guest has any non-`none`
level on that specific object.

Scope: notebook only. Dashboard, insight, and the scene-bound `/query/` rule (with the
embedded-resource AC cascade and query-body rescoper that go with them) land in a
follow-up PR — see #55468 description for the stack layout.
"""

import re
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from uuid import UUID

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect

from posthog.models import OrganizationMembership
from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.insight import Insight
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, UserAccessControl
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.notebooks.backend.models import Notebook
from products.surveys.backend.models import Survey

from ee.models.rbac.access_control import AccessControl


class GuestRule:
    """Base class for a guest deflection rule.

    Rules are tried in declaration order. The first rule whose `matches` returns a truthy
    match is the deciding rule: if its `allows` returns True the request is forwarded,
    otherwise the request is deflected. A request that matches no rule is deflected.

    `ac_pass_through=True` makes the rule the single source of truth for "guests can hit
    this endpoint past the resource-level AC check too" — when set and the rule allows,
    the middleware stamps a flag on the request that `AccessControlPermission` reads to
    skip its resource check. Use only for pure transforms / utilities that read no team
    data and have no side effects (e.g. schema-version migrations).
    """

    def __init__(self, pattern: str, *, ac_pass_through: bool = False):
        self._pattern = re.compile(pattern)
        self.ac_pass_through = ac_pass_through

    def matches(self, request: HttpRequest) -> re.Match | None:
        return self._pattern.match(request.path)

    def allows(self, request: HttpRequest, user: User, match: re.Match) -> bool:
        raise NotImplementedError


class AlwaysAllowed(GuestRule):
    """Identity, auth, static assets, the guest landing page, etc. — unconditionally allowed."""

    def allows(self, request: HttpRequest, user: User, match: re.Match) -> bool:
        return True


def _guest_membership_for_team(user: User, team_id: int) -> OrganizationMembership | None:
    """Fetch the guest membership tied to the org that owns this team, or `None` if the user
    isn't a guest there. Consolidates the `is_guest=True & correct org` lookup used by every
    rule below."""
    try:
        team = Team.objects.select_related("organization").get(id=team_id)
    except Team.DoesNotExist:
        return None
    return (
        OrganizationMembership.objects.filter(
            user=user,
            organization_id=team.organization_id,
            is_guest=True,
        )
        .select_related("organization")
        .first()
    )


def _has_any_team_ac_row(user: User, team_id: int) -> bool:
    """Does the guest have ANY AccessControl row scoped to this team? Used by the team-metadata
    rule — guests with zero grants have no business pulling team-wide metadata (themes, tags)."""
    membership = _guest_membership_for_team(user, team_id)
    if membership is None:
        return False
    return AccessControl.objects.filter(organization_member=membership, team_id=team_id).exists()


def _resolve_object(resource: str, resource_id: str, team_id: int):
    """Resolve a URL-style resource identifier to a concrete model instance we can pass to
    `UserAccessControl.access_level_for_object`. Returns `None` when the resource doesn't
    exist — the caller treats that as "not allowed" (guests can't enumerate)."""
    if resource == "notebook":
        # Notebook PK is a UUID, so an integer-style resource_id can only be a short_id.
        return Notebook.objects.filter(short_id=resource_id, team_id=team_id).first()
    if resource == "insight":
        # Insight URL form is short_id; an integer fallback covers numeric-id callers.
        obj = Insight.objects.filter(short_id=resource_id, team_id=team_id).first()
        if obj is None and resource_id.isdigit():
            obj = Insight.objects.filter(id=int(resource_id), team_id=team_id).first()
        return obj
    if resource == "feature_flag":
        if not resource_id.isdigit():
            return None
        return FeatureFlag.objects.filter(id=int(resource_id), team_id=team_id).first()
    if resource == "experiment":
        if not resource_id.isdigit():
            return None
        return Experiment.objects.filter(id=int(resource_id), team_id=team_id).first()
    if resource == "cohort":
        if not resource_id.isdigit():
            return None
        return Cohort.objects.filter(id=int(resource_id), team_id=team_id).first()
    if resource == "survey":
        # Survey PK is a UUID; the URL form is the UUID itself.
        return Survey.objects.filter(id=resource_id, team_id=team_id).first()
    if resource == "early_access_feature":
        # EAF PK is a UUID; the URL form is the UUID itself.
        return EarlyAccessFeature.objects.filter(id=resource_id, team_id=team_id).first()
    if resource == "session_recording":
        # SessionRecording lookup is by `session_id` (the URL key); PK is a UUID we don't see here.
        return SessionRecording.objects.filter(session_id=resource_id, team_id=team_id).first()
    if resource == "session_recording_playlist":
        # Playlist URL form is short_id.
        return SessionRecordingPlaylist.objects.filter(short_id=resource_id, team_id=team_id).first()
    return None


def _guest_has_access_to(user: User, team_id: int, resource: str, resource_id: str) -> bool:
    """Single decision point reused by every resource-bound rule.

    Returns True iff `UserAccessControl.access_level_for_object` resolves to a non-`none`
    level for the (guest, team, resource, resource_id) tuple.
    """
    membership = _guest_membership_for_team(user, team_id)
    if membership is None:
        return False
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return False

    obj = _resolve_object(resource, resource_id, team_id)
    if obj is None:
        return False

    uac = UserAccessControl(user=user, team=team)
    level = uac.access_level_for_object(obj, resource=resource)  # type: ignore[arg-type]
    return level is not None and level != NO_ACCESS_LEVEL


class TeamScopedMetadataRead(GuestRule):
    """GET-only team-scoped endpoints (themes, variables, tags, annotations, cohorts, quick filters).

    Insights and dashboards transitively depend on these to render. Allowed when the guest
    has any AC row on this team — otherwise they have no business reading team metadata.
    """

    def matches(self, request: HttpRequest) -> re.Match | None:
        if request.method != "GET":
            return None
        return super().matches(request)

    def allows(self, request: HttpRequest, user: User, match: re.Match) -> bool:
        team_id = int(match.group("team_id"))
        return _has_any_team_ac_row(user, team_id)


class TeamScopedPostSubAction(GuestRule):
    """POST-only team-scoped sub-actions that a viewer triggers automatically while
    interacting with granted resources. Same gate as `TeamScopedMetadataRead`: allowed
    iff the guest has any AC row on this team.

    These endpoints don't take a resource id and don't return resource data — the gate
    doesn't need to be tighter than "guest has any reason to be in this team."

    Today: `/query/upgrade/` (FE notebook migration step calls this for every non-saved
    embedded query when the scene loads; without this the granted notebook renders as
    NotFound for the guest it was shared with). Future: `/insights/cancel|timing|viewed`
    when dashboards / insights ship.
    """

    def matches(self, request: HttpRequest) -> re.Match | None:
        if request.method != "POST":
            return None
        return super().matches(request)

    def allows(self, request: HttpRequest, user: User, match: re.Match) -> bool:
        team_id = int(match.group("team_id"))
        return _has_any_team_ac_row(user, team_id)


class GrantBoundResource(GuestRule):
    """`/api/.../(dashboards|insights|notebooks)/<id>` — allowed iff the AC layer grants this
    guest non-`none` access to the addressed object.
    """

    def __init__(self, resource: str, pattern: str, *, ac_pass_through: bool = False):
        super().__init__(pattern, ac_pass_through=ac_pass_through)
        self._resource = resource

    def allows(self, request: HttpRequest, user: User, match: re.Match) -> bool:
        team_id = int(match.group("team_id"))
        resource_id = match.group("resource_id")
        return _guest_has_access_to(user, team_id, self._resource, resource_id)


class GrantBoundListFilter(GuestRule):
    """GET `/api/.../<resource>/?short_id=<id>` — FE scene loaders resolve by short_id. Allowed
    when the AC layer grants non-`none` access to the addressed object.
    """

    def __init__(self, resource: str, pattern: str, filter_key: str = "short_id", *, ac_pass_through: bool = False):
        super().__init__(pattern, ac_pass_through=ac_pass_through)
        self._resource = resource
        self._filter_key = filter_key

    def matches(self, request: HttpRequest) -> re.Match | None:
        if request.method != "GET":
            return None
        return super().matches(request)

    def allows(self, request: HttpRequest, user: User, match: re.Match) -> bool:
        filter_value = request.GET.get(self._filter_key)
        if not filter_value:
            return False
        team_id = int(match.group("team_id"))
        return _guest_has_access_to(user, team_id, self._resource, filter_value)


# `?scope=<X>&item_id=<id>` on the comments endpoint addresses the resource by
# its scope-specific item id form. Map the comment scope to the AC resource +
# item_id form expected by `_resolve_object`.
_COMMENT_SCOPE_TO_RESOURCE: dict[str, str] = {
    "Notebook": "notebook",
    "Replay": "session_recording",
    "Dashboard": "dashboard",
    "Insight": "insight",
    "FeatureFlag": "feature_flag",
    "Experiment": "experiment",
    "Survey": "survey",
}


class CommentScopeBoundRead(GuestRule):
    """GET `/api/.../comments/?scope=<X>&item_id=<id>` (and `comments/count`) — addresses a
    resource via the comment scope. Allowed iff the guest has an AC row on the addressed
    resource. Without a recognized scope+item_id pair the rule denies — guests have no
    business pulling un-scoped team-wide comment lists.
    """

    def matches(self, request: HttpRequest) -> re.Match | None:
        if request.method != "GET":
            return None
        return super().matches(request)

    def allows(self, request: HttpRequest, user: User, match: re.Match) -> bool:
        scope = request.GET.get("scope")
        item_id = request.GET.get("item_id")
        if not scope or not item_id:
            return False
        resource = _COMMENT_SCOPE_TO_RESOURCE.get(scope)
        if resource is None:
            return False
        team_id = int(match.group("team_id"))
        return _guest_has_access_to(user, team_id, resource, item_id)


_METADATA_ENDPOINTS = (
    "data_color_themes",
    "insight_variables",
    "quick_filters",
    "annotations",
    "cohorts",
    "tags",
    # `groups/find` and `groups/related` are GET-only resolver endpoints used by
    # ph-group / ph-group-properties / ph-related-groups embedded notebook nodes.
    # They take query params and return the addressed group; same gate as other
    # metadata reads — guest must hold any AC row on this team. The cascade
    # writes a `(group, str(group.pk))` AC row for these embeds so the resource
    # check at AccessControlPermission also passes.
    "groups/find",
    "groups/related",
    # Team-scoped feature-flag and experiment metadata reads. Each scene fans
    # out to the team-level config alongside the per-resource detail; the
    # AC layer's resource-level check + the cascade-written row on the
    # addressed feature_flag/experiment are what gate the actual data. These
    # endpoints return team-wide config (default release rules, eligible-flag
    # candidate lists), not per-resource secrets — same gate as other metadata.
    "default_release_conditions",
    "default_evaluation_contexts",
    "experiments/stats",
    "experiments/eligible_feature_flags",
    "experiment_holdouts",
    "experiment_saved_metrics",
    # GET-only resolver invoked from the notebook scene to find recording
    # comments embedded in any notebook the guest can read. The viewset's
    # queryset is filtered by `notebook` AC, so the guest only sees notebooks
    # they were granted — same gate as the rest of `/notebooks/`.
    "notebooks/recording_comments",
)


def _metadata_pattern(endpoint: str) -> str:
    return rf"^/api/(?:environments|projects)/(?P<team_id>\d+)/{endpoint}/?$"


GUEST_RULES: list[GuestRule] = [
    AlwaysAllowed(r"^/api/users/@me(/.*)?$"),
    AlwaysAllowed(r"^/api/organizations/@current/?$"),
    AlwaysAllowed(r"^/api/projects/@current/?$"),
    AlwaysAllowed(r"^/api/environments/@current/?$"),
    AlwaysAllowed(r"^/login/?$"),
    AlwaysAllowed(r"^/logout/?$"),
    AlwaysAllowed(r"^/api/login/?$"),
    AlwaysAllowed(r"^/api/logout/?$"),
    AlwaysAllowed(r"^/reset(/.*)?$"),
    AlwaysAllowed(r"^/signup/verify_email(/.*)?$"),
    AlwaysAllowed(r"^/_preflight/?$"),
    AlwaysAllowed(r"^/static/.*$"),
    AlwaysAllowed(r"^/favicon\.ico$"),
    AlwaysAllowed(r"^/guest(/.*)?$"),
    *[TeamScopedMetadataRead(_metadata_pattern(endpoint)) for endpoint in _METADATA_ENDPOINTS],
    TeamScopedPostSubAction(
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/query/upgrade/?$",
        ac_pass_through=True,
    ),
    GrantBoundResource(
        "notebook",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/notebooks/(?P<resource_id>[A-Za-z0-9-]+)/?$",
    ),
    # Notebook kernel status polling — bound to a granted notebook's short_id.
    # Same `_resolve_object` lookup as the detail GET; just a longer path.
    GrantBoundResource(
        "notebook",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/notebooks/(?P<resource_id>[A-Za-z0-9-]+)/kernel/status/?$",
    ),
    GrantBoundListFilter(
        "notebook",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/notebooks/?$",
    ),
    # Embedded-notebook-node resources. Each of these has an entry in
    # `NOTEBOOK_NODE_CASCADE` so that granting a notebook also writes a viewer-level
    # AC row for the addressed object — the rule below is the URL-side gate that
    # actually lets the guest reach the resource once that AC row exists.
    GrantBoundResource(
        "feature_flag",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/feature_flags/(?P<resource_id>\d+)/?$",
    ),
    # Sub-actions on a granted feature_flag. The viewset's `get_object()` runs the
    # AC layer's per-object check — same `(team, resource_id)` lookup as the detail
    # GET, just a longer path.
    GrantBoundResource(
        "feature_flag",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/feature_flags/(?P<resource_id>\d+)/status/?$",
    ),
    GrantBoundResource(
        "feature_flag",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/feature_flags/(?P<resource_id>\d+)/dependent_flags/?$",
    ),
    GrantBoundResource(
        "experiment",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/experiments/(?P<resource_id>\d+)/?$",
    ),
    GrantBoundResource(
        "cohort",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/cohorts/(?P<resource_id>\d+)/?$",
    ),
    GrantBoundResource(
        "survey",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/surveys/(?P<resource_id>[0-9a-f-]+)/?$",
    ),
    # Sub-action on a granted survey for the response-archive view.
    GrantBoundResource(
        "survey",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/surveys/(?P<resource_id>[0-9a-f-]+)/archived-response-uuids/?$",
    ),
    # `early_access_feature` is intentionally singular — that's the URL form the FE
    # currently hits. Don't pluralize without verifying the route.
    GrantBoundResource(
        "early_access_feature",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/early_access_feature/(?P<resource_id>[0-9a-f-]+)/?$",
    ),
    # SessionRecording IDs are posthog-js-generated session_ids — usually UUID-shaped
    # but not guaranteed. Allow the broader URL-safe charset.
    GrantBoundResource(
        "session_recording",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/session_recordings/(?P<resource_id>[A-Za-z0-9_-]+)/?$",
    ),
    # Replay snapshot payload — recording playback fans out to this after the metadata
    # GET. Same per-recording AC gate.
    GrantBoundResource(
        "session_recording",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/session_recordings/(?P<resource_id>[A-Za-z0-9_-]+)/snapshots/?$",
    ),
    GrantBoundResource(
        "session_recording_playlist",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/session_recording_playlists/(?P<resource_id>[A-Za-z0-9_-]+)/?$",
    ),
    # Some FE loaders fetch playlists by `?short_id=` against the list endpoint —
    # mirrors the notebook pattern.
    GrantBoundListFilter(
        "session_recording_playlist",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/session_recording_playlists/?$",
    ),
    # The async-refresh entry point for saved insights resolves by `?short_id=`
    # against the list endpoint. The cascade writes an `insight` AC row for each
    # `ph-query` SavedInsightNode embedded in a granted notebook, so this rule
    # passes only when the addressed insight is one of those.
    GrantBoundListFilter(
        "insight",
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/insights/?$",
    ),
    CommentScopeBoundRead(
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/comments/?$",
    ),
    CommentScopeBoundRead(
        r"^/api/(?:environments|projects)/(?P<team_id>\d+)/comments/count/?$",
    ),
]


# Patterns used to extract the org the request is targeting. Used by
# `GuestDeflectionMiddleware._target_organization_id` to scope the is_guest
# check to the right org — a user who is a guest of org A but a regular
# member of org B must not be deflected on org B's paths.
_TEAM_SCOPED_PATH_RE = re.compile(r"^/api/(?:projects|environments)/(?P<team_id>\d+)(?:/|$)")
_ORG_SCOPED_PATH_RE = re.compile(r"^/api/organizations/(?P<org_id>[0-9a-fA-F-]{36})(?:/|$)")


class GuestDeflectionMiddleware:
    """Deflects guest users from every endpoint not allowed by a rule in `GUEST_RULES`.

    Placement: after `AuthenticationMiddleware` (needs `request.user`) but before
    `ActiveOrganizationMiddleware` — same slot family as impersonation middlewares.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._rules: list[GuestRule] = GUEST_RULES

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not self._user_is_guest_for_request(request):
            return self.get_response(request)

        user = cast(User, request.user)
        for rule in self._rules:
            match = rule.matches(request)
            if not match:
                continue
            # First matching rule decides the outcome — a matched-but-denied rule
            # deflects rather than letting subsequent rules try the same path. Keeps
            # the rule table composable: a future rule added after a deny rule
            # cannot accidentally widen access for a path the deny rule already
            # decided on.
            if rule.allows(request, user, match):
                # Signal downstream `AccessControlPermission` to skip the resource-level
                # check for explicit pass-through endpoints (pure transforms / utilities).
                if rule.ac_pass_through:
                    request._guest_ac_pass_through = True  # type: ignore[attr-defined]
                return self.get_response(request)
            return self._deflect(request)

        return self._deflect(request)

    def _user_is_guest_for_request(self, request: HttpRequest) -> bool:
        """Should this request go through guest deflection?

        Yes when the user is a guest in the org the request targets, OR when the
        request path doesn't carry an org context (cross-org-safe fallback for
        identity / static / login routes already covered by AlwaysAllowed rules).

        No when the user is a guest in some *other* org but a regular member of
        the org this request targets — in that case guest deflection would
        wrongly 404 their normal-member access.
        """
        from posthog.rbac.guest_request_cache import get_user_guest_org_ids, is_user_guest_in_any_org

        if not is_user_guest_in_any_org(request):
            return False

        target_org_id = self._target_organization_id(request)
        if target_org_id is None:
            # Path doesn't name an org. Fall back to the rule loop so AlwaysAllowed
            # routes (login, /static, /guest, /api/users/@me/, etc.) still pass and
            # anything else gets deflected for safety.
            return True
        return target_org_id in get_user_guest_org_ids(request)

    def _target_organization_id(self, request: HttpRequest) -> "UUID | None":
        """Extract the organization the request is acting on, when possible.

        Returns the org for `/api/(projects|environments)/<team_id>/...` (resolved via
        the `Team` model) and for `/api/organizations/<org_id>/...` (direct UUID).
        Returns None for paths that don't carry an org/team identifier — the caller
        treats that as "fall through to the rule loop."
        """
        from uuid import UUID as _UUID

        team_match = _TEAM_SCOPED_PATH_RE.match(request.path)
        if team_match:
            try:
                team = Team.objects.select_related("organization").get(id=int(team_match.group("team_id")))
            except Team.DoesNotExist:
                return None
            return team.organization_id

        org_match = _ORG_SCOPED_PATH_RE.match(request.path)
        if org_match:
            raw = org_match.group("org_id")
            try:
                return _UUID(raw)
            except ValueError:
                return None

        return None

    def _deflect(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "Not found."}, status=404)
        # Defensive: /guest is covered by AlwaysAllowed above, but belt-and-suspenders —
        # returning 404 here prevents an infinite redirect loop if that rule is ever removed.
        if request.path.startswith("/guest"):
            return JsonResponse({"detail": "Not found."}, status=404)
        # `from=login` tells the landing scene this redirect is system-driven (post-login,
        # deep link to a forbidden path, etc.) so single-grant guests auto-jump to their
        # resource. The header "Shared with you" link omits the flag, ensuring user-initiated
        # navigation always shows the list. The SPA strips the flag after firing.
        return redirect("/guest?from=login")
