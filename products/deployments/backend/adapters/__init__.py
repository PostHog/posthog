"""External-system boundaries for the Deployments product.

Each adapter is a `typing.Protocol` that declares the surface area we need
from an external system (Cloudflare Pages, GitHub, microlink screenshots,
Temporal workflow control). Build/Infra and GitHub streams substitute real
implementations via `settings.DEPLOYMENTS_*_ADAPTER` (path-string → class)
without touching any of our files.

For tests and the dev environment, most adapters default to a `Null*` stub
that returns canned values. GitHub repository reads use the existing PostHog
GitHub integration by default, while deployment commit resolution remains
stubbed until the build stream owns that contract.
"""

from .cloudflare import (
    CloudflareAdapter,
    CloudflareError,
    CloudflarePagesAdapter,
    NullCloudflareAdapter,
    get_cloudflare_adapter,
)
from .github import GitHubAdapter, GitHubBranch, GitHubError, GitHubRepository, NullGitHubAdapter, get_github_adapter
from .microlink import NullScreenshotAdapter, ScreenshotAdapter, get_screenshot_adapter
from .temporal import NullWorkflowAdapter, TemporalWorkflowAdapter, WorkflowAdapter, WorkflowError, get_workflow_adapter

__all__ = [
    "CloudflareAdapter",
    "CloudflareError",
    "CloudflarePagesAdapter",
    "GitHubAdapter",
    "GitHubBranch",
    "GitHubError",
    "GitHubRepository",
    "NullCloudflareAdapter",
    "NullGitHubAdapter",
    "NullScreenshotAdapter",
    "NullWorkflowAdapter",
    "ScreenshotAdapter",
    "TemporalWorkflowAdapter",
    "WorkflowAdapter",
    "WorkflowError",
    "get_cloudflare_adapter",
    "get_github_adapter",
    "get_screenshot_adapter",
    "get_workflow_adapter",
]
