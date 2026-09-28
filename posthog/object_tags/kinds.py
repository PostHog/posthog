"""Single source of truth for the agent object-tag kind registry.

Agents cite PostHog objects in their replies with XML-style tags
(``<insight id="9pQx3">checkout funnel</insight>``). Each surface renders them
its own way — desktop as chips with hover previews, Slack and the web app as
markdown links — but they all share one vocabulary: the kinds, aliases, labels
and web paths defined here.

Every entry is declarative (path templates and regex strings, never code) so
``bin/build-object-tags-registry.py`` can emit the same registry for the
TypeScript consumers. After editing, run ``hogli build:object-tags`` and commit
the regenerated files:

- ``products/desktop/packages/core/src/inbox/objectKinds.generated.ts``
- ``products/desktop/packages/shared/src/objectTagKinds.generated.ts``
- ``frontend/src/lib/components/AgentObjectTags/objectKinds.generated.ts``

Python consumers import this module directly.
"""

import re
from functools import cache
from urllib.parse import quote

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


OBJECT_KINDS: dict[str, ObjectKindSpec] = {
    "insight": ObjectKindSpec(
        kind_label="Insight",
        source="Product analytics",
        path_template="/insights/{id}",
        block=True,
    ),
    "hogql": ObjectKindSpec(
        kind_label="SQL query",
        source="SQL editor",
        path_template="/sql?open_query={id}",
        block=True,
        id_is_body=True,
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
