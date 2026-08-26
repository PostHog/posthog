"""Facade for the context layer.

The presentation layer and other products (the tasks sandbox pipeline) reach
the store, pages, and enablement internals only through here.
"""

from __future__ import annotations

import uuid

from django.urls import reverse

import structlog

from posthog.dataclasses import frozen
from posthog.permissions import posthog_feature_flag_enabled

from products.context_layer.backend import store
from products.context_layer.backend.enablement import enable_context_layer
from products.context_layer.backend.models import ContextLayerConfig
from products.context_layer.backend.pages import (
    PAGE_MAX_BYTES,
    InvalidPagePathError,
    PageNotFoundError,
    WikiHealthFinding,
    WikiHealthReport,
    WikiPage,
    WikiTree,
    get_health_report,
    get_page,
    get_tree,
    page_frontmatter_channel_id,
    proposed_channel_page_path,
    resolve_channel_page,
    resolve_page_channel,
    write_page,
)
from products.context_layer.backend.store import (
    DREAM_BRANCH_RE,
    BundleConflictError,
    CommitAuthor,
    ContextLayerStoreError,
    HeadConflictError,
    LintFailedError,
    RepoLockUnavailableError,
    RepoNotFoundError,
    get_bundle_export,
    get_config,
    land_commit_bundle,
    land_dream_branch,
)

logger = structlog.get_logger(__name__)

CONTEXT_LAYER_FEATURE_FLAG = "context-layer"

# Where the wiki is cloned inside every sandbox, and the env vars agents use to
# find it and to land their commits back.
SANDBOX_MOUNT_PATH = "/tmp/workspace/context"
MOUNT_PATH_ENV_VAR = "POSTHOG_CONTEXT_LAYER_PATH"
COMMITS_PATH_ENV_VAR = "POSTHOG_CONTEXT_LAYER_COMMITS_PATH"

__all__ = [
    "COMMITS_PATH_ENV_VAR",
    "DREAM_BRANCH_RE",
    "CONTEXT_LAYER_FEATURE_FLAG",
    "MOUNT_PATH_ENV_VAR",
    "PAGE_MAX_BYTES",
    "SANDBOX_MOUNT_PATH",
    "BundleConflictError",
    "CommitAuthor",
    "ContextLayerMount",
    "ContextLayerStoreError",
    "HeadConflictError",
    "InvalidPagePathError",
    "LintFailedError",
    "PageNotFoundError",
    "RepoLockUnavailableError",
    "RepoNotFoundError",
    "WikiPage",
    "WikiHealthFinding",
    "WikiHealthReport",
    "WikiTree",
    "enable_context_layer",
    "get_bundle_export",
    "get_config",
    "get_page",
    "get_health_report",
    "get_sandbox_mount",
    "get_tree",
    "is_context_layer_enabled",
    "land_commit_bundle",
    "land_dream_branch",
    "page_frontmatter_channel_id",
    "proposed_channel_page_path",
    "resolve_channel_page",
    "resolve_page_channel",
    "sandbox_environment_variables",
    "write_page",
]


@frozen
class ContextLayerMount:
    """Everything a provisioner needs to clone the wiki into a sandbox."""

    bundle_url: str
    head_sha: str


def is_context_layer_enabled(*, organization_id: str, distinct_id: str) -> bool:
    """Org-gated opt-in for the context layer; fail-closed when evaluation fails."""
    try:
        return posthog_feature_flag_enabled(CONTEXT_LAYER_FEATURE_FLAG, distinct_id, organization_id=organization_id)
    except Exception:
        logger.exception("context_layer_flag_check_failed", organization_id=organization_id)
        return False


def sandbox_environment_variables(organization_id: uuid.UUID | str, team_id: int) -> dict[str, str]:
    """Env vars for a sandbox whose organization has a wiki; empty when it does
    not exist yet. Callers gate on the feature flag.

    The commits path is the project-nested agent route, because the run token
    carries `scoped_teams` and the organization-nested route refuses it."""
    if not ContextLayerConfig.objects.filter(organization_id=organization_id).exists():
        return {}
    return {
        MOUNT_PATH_ENV_VAR: SANDBOX_MOUNT_PATH,
        COMMITS_PATH_ENV_VAR: reverse("project_context_layer-commits", kwargs={"parent_lookup_team_id": str(team_id)}),
    }


def get_sandbox_mount(organization_id: uuid.UUID | str) -> ContextLayerMount | None:
    """A short-lived bundle URL for cloning the wiki into a sandbox, or None
    when the organization has no wiki. The presign is minted here, at clone
    time, so the sandbox never holds storage credentials."""
    try:
        export = store.get_bundle_export(organization_id)
    except store.ContextLayerStoreError:
        return None
    return ContextLayerMount(bundle_url=export.url, head_sha=export.head_sha)
