"""Facade for the context layer.

The presentation layer (and, in later layers, other products) reaches the
store, pages, and enablement internals only through here.
"""

from products.context_layer.backend.enablement import (
    RestrictedProjectsError,
    enable_context_layer,
    organization_has_private_projects,
)
from products.context_layer.backend.pages import (
    PAGE_MAX_BYTES,
    InvalidPagePathError,
    PageNotFoundError,
    WikiPage,
    WikiTree,
    get_page,
    get_tree,
    write_page,
)
from products.context_layer.backend.store import (
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
)

__all__ = [
    "PAGE_MAX_BYTES",
    "BundleConflictError",
    "CommitAuthor",
    "ContextLayerStoreError",
    "HeadConflictError",
    "InvalidPagePathError",
    "LintFailedError",
    "PageNotFoundError",
    "RepoLockUnavailableError",
    "RepoNotFoundError",
    "RestrictedProjectsError",
    "WikiPage",
    "WikiTree",
    "enable_context_layer",
    "get_bundle_export",
    "get_config",
    "get_page",
    "get_tree",
    "organization_has_private_projects",
    "land_commit_bundle",
    "write_page",
]
