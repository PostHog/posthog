"""Notebook embedded-node AC cascade.

When a guest is granted a notebook, the notebook's content tree may embed other
resources (saved insights, recordings, cohorts, feature flags, etc.). For those
embeds to render server-side, the guest needs an `AccessControl` row on each
embedded resource at viewer level — the same pattern used for dashboard-tile
cascade.

`NOTEBOOK_NODE_CASCADE` is the single source of truth for which TipTap node types
participate in the cascade and how the resource id is extracted from `attrs`.
Adding a new embed type that should grant transitive read access is a one-row
addition here. Removing a row collapses the cascade for that node type.

Scope/limitations (v1):
- Cascade fires only at grant creation time (invite acceptance, future
  `add_grant_to_membership`). Notebook content edits that introduce *new* embeds
  do NOT auto-grant access — that's a follow-up. Same for unlinking embeds via
  edit / soft-delete: the AC rows persist until promote-to-member or
  remove-from-org sweeps them.
- The middleware rule for the embedded resource's URL is what actually lets the
  guest reach the data — the cascade only writes AC rows. Resources whose URL
  rules haven't landed yet (insight, dashboard, recording, etc.) get their AC
  rows here but are still middleware-deflected; they become reachable when the
  matching middleware rule lands in a follow-up.
- Backlink cascade is shallow (one hop). A backlink to notebook B from granted
  notebook A writes one AC row for notebook B; B's own embeds aren't recursively
  walked.
"""

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.models import OrganizationMembership
    from posthog.models.team.team import Team
    from posthog.models.user import User

    from products.notebooks.backend.models import Notebook


# Each entry: notebook node `type` (the TipTap node type string, mirrors
# `NotebookNodeType` on the FE) -> (`resource`, `extract_id`).
#
# `resource` is the AC resource name written into `AccessControl.resource`.
# `extract_id` reads the node's `attrs` dict and returns a URL-style id (short_id
# for short-id-addressed models, stringified PK otherwise) or None when the node
# doesn't carry an actionable id (e.g. an inline query that doesn't reference a
# saved insight). The PK resolution from URL-style id happens in
# `_resolve_to_ac_pk` so the table stays declarative.

NodeAttrs = dict[str, Any]
IdExtractor = Callable[[NodeAttrs], str | None]


def _extract_id(attrs: NodeAttrs) -> str | None:
    """Most embed nodes store the resource id as `attrs.id`."""
    value = attrs.get("id")
    return str(value) if value else None


def _extract_group_composite_id(attrs: NodeAttrs) -> str | None:
    """`ph-group` / `ph-group-properties` / `ph-related-groups` nodes carry
    `{ id: <group_key>, groupTypeIndex: <int> }`. The Group model is keyed by
    `(team, group_type_index, group_key)`; we encode the pair as a composite
    string for the walker, then `_resolve_to_ac_pk` looks up the integer Group
    PK and that's what lands in the AC table."""
    group_key = attrs.get("id")
    group_type_index = attrs.get("groupTypeIndex")
    if not group_key or group_type_index is None:
        return None
    return f"{group_type_index}:{group_key}"


def _extract_query_short_id(attrs: NodeAttrs) -> str | None:
    """`ph-query` nodes embed a SavedInsightNode by short_id under `attrs.query.shortId`.
    Inline queries (HogQLQuery, EventsQuery, etc.) carry no insight reference and
    are intentionally non-cascadeable — the query rescoper handles those."""
    query = attrs.get("query")
    if not isinstance(query, dict) or query.get("kind") != "SavedInsightNode":
        return None
    short_id = query.get("shortId")
    return str(short_id) if short_id else None


def _extract_playlist_short_id(attrs: NodeAttrs) -> str | None:
    """`ph-recording-playlist` nodes carry the playlist short_id under
    `attrs.playlistShortId` (matching the URL form). Fall back to `attrs.id` for
    older content shapes that may have stored it there."""
    value = attrs.get("playlistShortId") or attrs.get("id")
    return str(value) if value else None


NOTEBOOK_NODE_CASCADE: dict[str, tuple[str, IdExtractor]] = {
    "ph-query": ("insight", _extract_query_short_id),
    "ph-recording": ("session_recording", _extract_id),
    "ph-recording-playlist": ("session_recording_playlist", _extract_playlist_short_id),
    "ph-cohort": ("cohort", _extract_id),
    "ph-feature-flag": ("feature_flag", _extract_id),
    "ph-feature-flag-code-example": ("feature_flag", _extract_id),
    "ph-experiment": ("experiment", _extract_id),
    "ph-early-access-feature": ("early_access_feature", _extract_id),
    "ph-survey": ("survey", _extract_id),
    # Group embeds — written as `(group, str(group.pk))` rows so the AC layer's
    # `has_any_specific_access_for_resource("group", ...)` returns true and the
    # `groups/find` / `groups/related` resolvers stop 403'ing on guests. The
    # composite `<group_type_index>:<group_key>` URL id is resolved to the
    # integer Group PK in `_resolve_to_ac_pk`.
    "ph-group": ("group", _extract_group_composite_id),
    "ph-group-properties": ("group", _extract_group_composite_id),
    "ph-related-groups": ("group", _extract_group_composite_id),
    # Backlink to another notebook: shallow (1 hop) cascade.
    "ph-backlink": ("notebook", _extract_id),
}


def walk_notebook_content_for_grants(content: Any) -> list[tuple[str, str]]:
    """Walk a notebook's TipTap content tree and return the deduplicated list of
    `(resource, url_id)` tuples for each cascadeable embedded node found.

    Returns the list sorted for deterministic ordering (tests + log diffs)."""
    if not isinstance(content, dict):
        return []

    seen: set[tuple[str, str]] = set()

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        entry = NOTEBOOK_NODE_CASCADE.get(node_type) if isinstance(node_type, str) else None
        if entry is not None:
            resource, extract = entry
            attrs = node.get("attrs") or {}
            if isinstance(attrs, dict):
                url_id = extract(attrs)
                if url_id:
                    seen.add((resource, url_id))
        children = node.get("content")
        if isinstance(children, list):
            for child in children:
                visit(child)

    visit(content)
    return sorted(seen)


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _resolve_to_ac_pk(resource: str, url_id: str, team_id: int) -> str | None:
    """Translate a URL-style id (as found in node attrs) into the AC table's
    `resource_id` (which is always the model PK as a string).

    Returns None when the target doesn't exist in this team — the caller skips
    it (no AC row written for ghost references)."""
    from posthog.models.group.group import Group
    from posthog.models.insight import Insight
    from posthog.session_recordings.models.session_recording import SessionRecording
    from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

    from products.notebooks.backend.models import Notebook

    if resource == "group":
        # Composite `<group_type_index>:<group_key>` from the walker → integer Group PK.
        # Group_key may legitimately contain colons (e.g. urn-style ids), so split once.
        if ":" not in url_id:
            return None
        group_type_index_str, group_key = url_id.split(":", 1)
        if not group_type_index_str.isdigit() or not group_key:
            return None
        pk = (
            Group.objects.filter(
                team_id=team_id,
                group_type_index=int(group_type_index_str),
                group_key=group_key,
            )
            .values_list("id", flat=True)
            .first()
        )
        return str(pk) if pk is not None else None
    if resource == "insight":
        pk = Insight.objects.filter(short_id=url_id, team_id=team_id).values_list("id", flat=True).first()
        if pk is None and url_id.isdigit():
            pk = Insight.objects.filter(id=int(url_id), team_id=team_id).values_list("id", flat=True).first()
        return str(pk) if pk is not None else None
    if resource == "notebook":
        # Notebook PK is a UUID; URL form is short_id.
        pk = Notebook.objects.filter(short_id=url_id, team_id=team_id).values_list("id", flat=True).first()
        return str(pk) if pk is not None else None
    if resource == "session_recording_playlist":
        # Playlist URL form is short_id; PK is the integer id we write to AC.
        pk = (
            SessionRecordingPlaylist.objects.filter(short_id=url_id, team_id=team_id)
            .values_list("id", flat=True)
            .first()
        )
        return str(pk) if pk is not None else None
    if resource == "session_recording":
        # SessionRecording URL form is `session_id`; the AC layer addresses by the
        # UUID PK (`obj.id`), so resolve the embed's session_id to the recording's
        # PK and write THAT into the AC table.
        pk = SessionRecording.objects.filter(session_id=url_id, team_id=team_id).values_list("id", flat=True).first()
        return str(pk) if pk is not None else None
    # All other resources (cohort, feature_flag, experiment) use integer PKs in URL form.
    # Survey / EAF use UUID PKs in URL form. Pass through numeric and UUID-shaped values;
    # reject anything else (defensive — we don't enumerate every model here, so an
    # unrecognized shape stays unwritten rather than corrupting the AC table).
    if url_id.isdigit():
        return url_id
    if _UUID_RE.match(url_id):
        return url_id
    return None


def cascade_grants_for_notebook(
    *,
    notebook: "Notebook",
    membership: "OrganizationMembership",
    team: "Team",
    created_by: "User",
    access_level: str = "viewer",
) -> int:
    """Write one viewer-level AC row per cascadeable embedded resource referenced
    by this notebook's content. Returns the number of rows written or updated.

    The embedded resources are pinned to viewer regardless of the parent grant's
    level — embedding a resource into a notebook is a *read* contract; the guest
    doesn't inherit edit rights on the embedded resource."""
    from ee.models.rbac.access_control import AccessControl

    written = 0
    for resource, url_id in walk_notebook_content_for_grants(notebook.content):
        ac_resource_id = _resolve_to_ac_pk(resource, url_id, team.id)
        if ac_resource_id is None:
            continue
        AccessControl.objects.get_or_create(
            team=team,
            resource=resource,
            resource_id=ac_resource_id,
            organization_member=membership,
            role=None,
            defaults={"access_level": access_level, "created_by": created_by},
        )
        written += 1
    return written


__all__ = [
    "NOTEBOOK_NODE_CASCADE",
    "cascade_grants_for_notebook",
    "walk_notebook_content_for_grants",
]
