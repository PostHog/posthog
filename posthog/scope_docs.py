"""What each exposed API scope object is for, in words a person choosing scopes can use.

Each product declares the scope objects it owns in `products/<name>/backend/scopes.py`, as a
`SCOPE_DOCS` sequence discovered the way `routes.py` is. Scope objects that core owns are declared
here. Every object in `EXPOSED_SCOPE_OBJECTS` needs exactly one declaration, which
`posthog/test/repo_invariants/test_scope_docs.py` enforces.

The same declarations feed the web app's scope pickers (through `scope_docs_projection.py`),
the public `/oauth/scopes/` endpoint, and the scope reference on posthog.com.
"""

from collections.abc import Iterable
from typing import Literal, get_args

from posthog.dataclasses import frozen
from posthog.products import load_product_modules
from posthog.scopes import ALL_SCOPES, API_SCOPE_ACTIONS, APIScopeActions, APIScopeObject

DOCS_URL_PREFIX = "https://posthog.com/docs/"
MAX_DESCRIPTION_LENGTH = 120

# The product areas scope pickers group objects under, in the order they show. A group is an area a
# person recognizes, not a code module or a team, so add one only when two or more objects need it.
ScopeGroup = Literal[
    "Product analytics",
    "Web, marketing & revenue analytics",
    "Events, people & data model",
    "Session replay",
    "Feature flags, experiments & surveys",
    "Error tracking, logs & tracing",
    "Developer experience",
    "LLM & MCP analytics",
    "Data warehouse & pipelines",
    "Messaging",
    "AI & context management tools",
    "Customers & support",
    "Setup & data management",
    "Organization & account",
]
SCOPE_GROUPS: tuple[ScopeGroup, ...] = get_args(ScopeGroup)


@frozen
class ScopeDependency:
    # The scope the dependent scope also needs, such as "feature_flag:write".
    scope: str
    # One sentence on why, which pickers show next to the level that needs it.
    reason: str


@frozen
class ScopeDoc:
    object: APIScopeObject
    # The name scope pickers show, in sentence case, such as "Feature flag".
    name: str
    # The plural that fits in a sentence, lowercase except for proper nouns and acronyms, such as
    # "feature flags" or "LLM prompts".
    plural: str
    # One sentence on what the scope covers, without "read" or "write": every surface that shows it
    # adds the access level itself.
    description: str
    group: ScopeGroup
    docs_url: str | None = None
    # The access levels a picker offers. An object whose endpoints only read, or only act, offers one.
    actions: tuple[APIScopeActions, ...] = ("read", "write")
    # The scope reaches past a single project, so a key limited to some projects cannot take it.
    organization_wide: bool = False
    # A scope that writing this object also needs, such as the feature flag a survey writes. The key
    # picker selects it with write access and shows the reason.
    write_requires: ScopeDependency | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.plural.strip():
            raise ValueError(f"ScopeDoc for {self.object!r} needs a name and a plural")
        if not self.actions or not set(self.actions) <= set(API_SCOPE_ACTIONS):
            raise ValueError(f"ScopeDoc for {self.object!r} needs actions from {API_SCOPE_ACTIONS}")
        if not self.description.endswith(".") or len(self.description) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"ScopeDoc for {self.object!r} needs a description of one sentence ending with a period,"
                f" at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        if "—" in self.description or "–" in self.description:
            raise ValueError(f"ScopeDoc for {self.object!r} uses a dash; rewrite the description without one")
        if self.docs_url is not None and not self.docs_url.startswith(DOCS_URL_PREFIX):
            raise ValueError(f"ScopeDoc for {self.object!r} must link to a page under {DOCS_URL_PREFIX}")
        if self.group not in SCOPE_GROUPS:
            raise ValueError(f"ScopeDoc for {self.object!r} needs a group from SCOPE_GROUPS")
        if self.write_requires is not None and (
            "write" not in self.actions or self.write_requires.scope not in ALL_SCOPES
        ):
            raise ValueError(f"ScopeDoc for {self.object!r} has write_requires without write, or on an unknown scope")


CORE_SCOPE_DOCS: tuple[ScopeDoc, ...] = (
    ScopeDoc(
        object="activity_log",
        name="Activity log",
        plural="activity logs",
        description="The project's activity log of changes to resources, with filters and exports.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/settings/activity-logs",
    ),
    ScopeDoc(
        object="billing",
        name="Billing",
        plural="billing",
        description="The organization's subscription, usage, spend, forecasts, invoices, and limits, across all its projects.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/billing/common-questions",
    ),
    ScopeDoc(
        object="cohort",
        name="Cohort",
        plural="cohorts",
        description="Cohorts, including their filters, static member lists, calculation history, and where they are used.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/data/cohorts",
    ),
    ScopeDoc(
        object="comment",
        name="Comment",
        plural="comments",
        description="Comments and discussion threads on PostHog resources, including resolving them and mirroring them to Slack.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/data/comments",
    ),
    ScopeDoc(
        object="conversation",
        name="AI conversation",
        plural="AI conversations",
        description="PostHog AI chat conversations, including starting them, sending messages, and canceling or queueing replies.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/posthog-ai",
    ),
    ScopeDoc(
        object="data_deletion",
        name="Data deletion",
        plural="data deletion requests",
        description="Requests to delete events, event properties, or persons from a project, with previews of the affected data.",
        group="Setup & data management",
    ),
    ScopeDoc(
        object="element",
        name="Element",
        plural="elements",
        description="Autocaptured page elements, with the click stats and values used by heatmaps and the toolbar.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/product-analytics/autocapture",
    ),
    ScopeDoc(
        object="event_definition",
        name="Event definition",
        plural="event definitions",
        description="Event definitions, schemas, and property groups, including tags, verification, and generated type definitions.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/data/events",
    ),
    ScopeDoc(
        object="event_filter",
        name="Event filter",
        plural="event filters",
        description="The project's ingestion filter that drops matching events, plus its dry-run and drop metrics.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/data/event-filtering",
    ),
    ScopeDoc(
        object="file_system",
        name="File system",
        plural="file system items",
        description="The project file tree: folders, saved items, search, and recently viewed files.",
        group="Organization & account",
        actions=("read",),
    ),
    ScopeDoc(
        object="file_system_shortcut",
        name="File system shortcut",
        plural="file system shortcuts",
        description="Shortcuts pinned to items in the project file tree.",
        group="Organization & account",
    ),
    ScopeDoc(
        object="health_issue",
        name="Health issue",
        plural="health issues",
        description="Problems found by project health checks, such as outdated SDKs or failing syncs, and snoozing them.",
        group="Setup & data management",
        docs_url="https://posthog.com/docs/health-checks",
    ),
    ScopeDoc(
        object="ingestion_warning",
        name="Ingestion warning",
        plural="ingestion warnings",
        description="Ingestion warnings for events and person or group updates that were ingested with problems.",
        group="Setup & data management",
        docs_url="https://posthog.com/docs/data/ingestion-warnings",
        actions=("read",),
    ),
    ScopeDoc(
        object="integration",
        name="Integration",
        plural="integrations",
        description="Project integrations with third-party services such as Slack, plus connections to other PostHog projects.",
        group="Setup & data management",
    ),
    ScopeDoc(
        object="llm_gateway",
        name="LLM gateway",
        plural="LLM gateway",
        description="Sending LLM requests through the PostHog LLM gateway, where PostHog has enabled it.",
        group="LLM & MCP analytics",
        actions=("read",),
    ),
    ScopeDoc(
        object="organization",
        name="Organization",
        plural="organizations",
        description="Organization settings, verified domains, roles, SSO providers, and proxies, across the whole organization.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/settings/organizations",
        organization_wide=True,
    ),
    ScopeDoc(
        object="organization_integration",
        name="Organization integration",
        plural="organization integrations",
        description="Organization-wide integrations, such as Vercel or AWS Marketplace, including disconnecting them.",
        group="Setup & data management",
        docs_url="https://posthog.com/docs/integrations/vercel-marketplace",
        organization_wide=True,
    ),
    ScopeDoc(
        object="organization_member",
        name="Organization member",
        plural="organization members",
        description="Organization members and invites, including membership levels and removing members.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/settings/organizations",
        organization_wide=True,
    ),
    ScopeDoc(
        object="person",
        name="Person",
        plural="persons",
        description="Persons and their properties, including updating, splitting, and deleting persons and their data.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/data/persons",
    ),
    ScopeDoc(
        object="product_enablement",
        name="Product enablement",
        plural="product enablement",
        description="Turning on products such as Session replay, Error tracking, and Conversations for a project.",
        group="Setup & data management",
        actions=("write",),
    ),
    ScopeDoc(
        object="project",
        name="Project",
        plural="projects",
        description="Projects and their settings, including how data is ingested, plus creating and modifying projects.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/settings/projects",
    ),
    ScopeDoc(
        object="property_definition",
        name="Property definition",
        plural="property definitions",
        description="Event and person property definitions, including their descriptions, types, tags, and verification status.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/data",
    ),
    ScopeDoc(
        object="query",
        name="Query",
        plural="queries",
        description="Running SQL and insight queries on your project's data, plus event, session, and web vitals lookups.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/api/queries",
        actions=("read",),
    ),
    ScopeDoc(
        object="session_recording",
        name="Session recording",
        plural="session recordings",
        description="Session recordings, including their snapshots, console logs, viewed status, and deletion.",
        group="Session replay",
        docs_url="https://posthog.com/docs/session-replay",
    ),
    ScopeDoc(
        object="session_recording_playlist",
        name="Session recording playlist",
        plural="session recording playlists",
        description="Session replay collections and saved filters, including the recordings added to them.",
        group="Session replay",
        docs_url="https://posthog.com/docs/session-replay",
    ),
    ScopeDoc(
        object="sharing_configuration",
        name="Sharing configuration",
        plural="sharing configurations",
        description="Public sharing and embed settings for dashboards, insights, recordings, and notebooks, including passwords.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/product-analytics/sharing",
    ),
    ScopeDoc(
        object="uploaded_media",
        name="Uploaded media",
        plural="uploaded media",
        description="Images uploaded to your project, such as those in dashboard text cards, including uploads and deletion.",
        group="Organization & account",
    ),
    ScopeDoc(
        object="user",
        name="User",
        plural="users",
        description="Your own user account, including profile, settings, two-factor setup, login sessions, and integrations.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/settings/account-settings",
        actions=("read",),
    ),
    ScopeDoc(
        object="workload_trust_policy",
        name="Workload trust policy",
        plural="workload trust policies",
        description="Trust policies that let workloads such as CI jobs exchange an OIDC token for a PostHog project token.",
        group="Organization & account",
        actions=("read",),
    ),
    ScopeDoc(
        object="workload_trust_policy_request",
        name="Workload trust policy request",
        plural="workload trust policy requests",
        description="Requests asking an organization admin for a workload trust policy, and approving or rejecting them.",
        group="Organization & account",
    ),
)


def collect_scope_docs(product_declarations: Iterable[Iterable[ScopeDoc]]) -> dict[APIScopeObject, ScopeDoc]:
    """Index core's declarations and the given product ones by scope object, sorted by object,
    refusing an object declared twice."""
    collected: dict[APIScopeObject, ScopeDoc] = {}
    for declaration in [CORE_SCOPE_DOCS, *product_declarations]:
        for doc in declaration:
            if doc.object in collected:
                raise ValueError(f"Scope object {doc.object!r} is declared more than once")
            collected[doc.object] = doc
    return dict(sorted(collected.items()))


_scope_docs: dict[APIScopeObject, ScopeDoc] | None = None


def get_scope_docs() -> dict[APIScopeObject, ScopeDoc]:
    """Every declared ScopeDoc: core's and each installed product's. The declarations are fixed at
    import time, so they are collected once per process."""
    global _scope_docs
    if _scope_docs is None:
        product_declarations = [getattr(module, "SCOPE_DOCS", ()) for module in load_product_modules("scopes")]
        _scope_docs = collect_scope_docs(product_declarations)
    return _scope_docs
