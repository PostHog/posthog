"""Single source of truth for the agent object-tag kind registry.

Agents cite PostHog objects in their replies with XML-style tags
(``<insight id="9pQx3">checkout funnel</insight>``). Each surface renders them
its own way — desktop as chips with hover previews, Slack and the web app as
markdown links — but they all share one vocabulary: the kinds, aliases, labels
and web paths defined here.

Every entry is declarative (path templates and regex strings, never code) so
``posthog/object_tags/projection.py`` can emit the same registry for the
TypeScript consumers. After editing, run ``hogli build:projections`` and commit
the regenerated files:

- ``products/desktop/packages/core/src/inbox/objectKinds.generated.ts``
- ``packages/agent/packages/agent-contracts/src/objectTagKinds.generated.ts``
- ``frontend/src/lib/components/AgentObjectTags/objectKinds.generated.ts``

Python consumers import this module directly.
"""

import re
import json
from functools import cache
from urllib.parse import parse_qs, quote, unquote, urlsplit

from posthog.dataclasses import frozen


@frozen
class ObjectKindSpec:
    """One agent-citable object kind."""

    kind_label: str
    # Product the object comes from, e.g. "Product analytics".
    source: str
    # Project-relative page template where ``{id}`` is the URL-encoded object id,
    # or None when the kind has no canonical page.
    path_template: str | None = None
    # When set, the raw id must match for the kind to have a page at all
    # (e.g. flag pages resolve by numeric id only, not by key). Must stay in the
    # re/JS-RegExp common subset with no flags, so spell out case variants inline.
    id_pattern: str | None = None
    # display="block" renders as a full card on surfaces that support it.
    block: bool = False
    # The tag body is the object id itself rather than a label (hogql: the SQL).
    id_is_body: bool = False
    url_aliases: tuple[str, ...] = ()


OBJECT_KINDS: dict[str, ObjectKindSpec] = {
    "insight": ObjectKindSpec(
        kind_label="Insight",
        source="Product analytics",
        path_template="/insights/{id}",
        block=True,
        url_aliases=("/i/{id}",),
    ),
    "hogql": ObjectKindSpec(
        kind_label="SQL query",
        source="SQL editor",
        path_template="/sql?open_query={id}",
        block=True,
        id_is_body=True,
        url_aliases=("/insights/new#q={query}",),
    ),
    "dashboard": ObjectKindSpec(
        kind_label="Dashboard",
        source="Product analytics",
        path_template="/dashboard/{id}",
    ),
    "error": ObjectKindSpec(
        kind_label="Error issue",
        source="Error tracking",
        path_template="/error_tracking/{id}",
    ),
    "replay": ObjectKindSpec(
        kind_label="Session replay",
        source="Session replay",
        path_template="/replay/{id}",
        block=True,
        url_aliases=("/replay/home?sessionRecordingId={id}",),
    ),
    "flag": ObjectKindSpec(
        kind_label="Feature flag",
        source="Feature flags",
        path_template="/feature_flags/{id}",
        id_pattern=r"^\d+$",
    ),
    "experiment": ObjectKindSpec(
        kind_label="Experiment",
        source="Experiments",
        path_template="/experiments/{id}",
    ),
    "survey": ObjectKindSpec(
        kind_label="Survey",
        source="Surveys",
        path_template="/surveys/{id}",
    ),
    "ticket": ObjectKindSpec(
        kind_label="Support tickets",
        source="Conversations",
        path_template="/support/tickets/{id}",
    ),
    "report": ObjectKindSpec(
        kind_label="Inbox report",
        source="Inbox",
        path_template="/inbox/{id}",
    ),
    "trace": ObjectKindSpec(
        kind_label="LLM trace",
        source="AI observability",
        path_template="/ai-observability/traces/{id}",
    ),
    "eval": ObjectKindSpec(
        kind_label="Evaluation",
        source="AI evals",
        path_template="/ai-evals/evaluations/{id}",
    ),
    "event": ObjectKindSpec(
        kind_label="Events",
        source="Product analytics",
        path_template="/data-management/events/{id}",
        # Event definition pages resolve by uuid; an event cited by name has no page.
        id_pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}$",
    ),
    "cohort": ObjectKindSpec(
        kind_label="Cohort",
        source="Product analytics",
        path_template="/cohorts/{id}",
    ),
    "action": ObjectKindSpec(
        kind_label="Action",
        source="Product analytics",
        path_template="/data-management/actions/{id}",
    ),
    "person": ObjectKindSpec(
        kind_label="Person",
        source="Product analytics",
        path_template="/persons/{id}",
    ),
}

# Alternate tag names agents plausibly write, mapped to registry kinds.
OBJECT_KIND_ALIASES: dict[str, str] = {
    "session-replay": "replay",
    "session_replay": "replay",
    "recording": "replay",
    "feature-flag": "flag",
    "feature_flag": "flag",
    "sql": "hogql",
}

RESERVED_URL_IDS: tuple[str, ...] = ("new", "home", "playlists", "settings", "configuration", "options")

APP_HOST_ALIASES: dict[str, str] = {"app.posthog.com": "us.posthog.com"}

# Rendering fallback for a tag whose kind nobody registered.
FALLBACK_OBJECT_KIND = ObjectKindSpec(kind_label="Evidence", source="PostHog")


def resolve_object_kind(name: str) -> ObjectKindSpec | None:
    """Spec for a tag name (alias-aware), or None when it isn't an object tag."""
    return OBJECT_KINDS.get(OBJECT_KIND_ALIASES.get(name, name))


@cache
def _compiled_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def object_web_path(spec: ObjectKindSpec, object_id: str) -> str | None:
    """Project-relative page path for an object id, or None when it has no page."""
    if spec.path_template is None:
        return None
    if spec.id_pattern is not None and not _compiled_pattern(spec.id_pattern).match(object_id):
        return None
    return spec.path_template.replace("{id}", quote(object_id, safe=""))


@frozen
class ObjectUrlMatch:
    kind: str
    object_id: str


def _app_host(netloc: str) -> str:
    host = netloc.lower()
    return APP_HOST_ALIASES.get(host, host)


def _path_segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def _hogql_from_query_node(raw: str) -> str | None:
    try:
        node = json.loads(raw)
    except ValueError:
        return None
    for _ in range(3):
        if not isinstance(node, dict):
            return None
        if node.get("kind") == "HogQLQuery" and isinstance(node.get("query"), str):
            return node["query"]
        node = node.get("source")
    return None


def _match_url_template(template: str, segments: list[str], query: str, fragment: str) -> str | None:
    parts = urlsplit(template)
    template_segments = _path_segments(parts.path)
    if "{id}" in template_segments:
        index = template_segments.index("{id}")
        if len(segments) <= index or segments[:index] != template_segments[:index]:
            return None
        value = unquote(segments[index])
        return None if value in RESERVED_URL_IDS else value
    if segments != template_segments:
        return None
    for template_params, url_params in ((parts.query, query), (parts.fragment, fragment)):
        if not template_params:
            continue
        key, _, placeholder = template_params.partition("=")
        values = parse_qs(url_params).get(key)
        if not values:
            return None
        return _hogql_from_query_node(values[0]) if placeholder == "{query}" else values[0]
    return None


def parse_object_url(url: str, *, project_url: str) -> ObjectUrlMatch | None:
    try:
        target = urlsplit(url.strip())
        base = urlsplit(project_url)
    except ValueError:
        return None
    if target.scheme not in ("http", "https") or _app_host(target.netloc) != _app_host(base.netloc):
        return None
    segments = _path_segments(target.path)
    base_segments = _path_segments(base.path)
    if segments[:1] == ["project"]:
        if segments[:2] != base_segments[:2]:
            return None
        segments = segments[2:]
    for name, spec in OBJECT_KINDS.items():
        for template in (spec.path_template, *spec.url_aliases):
            if template is None:
                continue
            value = _match_url_template(template, segments, target.query, target.fragment)
            if value and spec.id_is_body and value.lstrip().startswith("{"):
                value = _hogql_from_query_node(value)
            object_id = (value or "").strip()
            if not object_id:
                continue
            if spec.id_pattern is not None and not _compiled_pattern(spec.id_pattern).match(object_id):
                continue
            return ObjectUrlMatch(kind=name, object_id=object_id)
    return None
