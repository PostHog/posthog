"""External-system boundaries for the Deployments product.

Each adapter is a `typing.Protocol` that declares the surface area we need
from an external system (Cloudflare Pages, GitHub, microlink screenshots,
Temporal workflow control). Build/Infra and GitHub streams substitute real
implementations via `settings.DEPLOYMENTS_*_ADAPTER` (path-string → class)
without touching any of our files.

For tests and the dev environment, a `Null*` stub is the default — it
returns canned values so the rest of the codebase exercises real code
paths without standing up external services.
"""

from .cloudflare import CloudflareAdapter, CloudflareError, NullCloudflareAdapter, get_cloudflare_adapter
from .github import GitHubAdapter, GitHubError, NullGitHubAdapter, get_github_adapter
from .microlink import NullScreenshotAdapter, ScreenshotAdapter, get_screenshot_adapter
from .temporal import NullWorkflowAdapter, WorkflowAdapter, WorkflowError, get_workflow_adapter

__all__ = [
    "CloudflareAdapter",
    "CloudflareError",
    "GitHubAdapter",
    "GitHubError",
    "NullCloudflareAdapter",
    "NullGitHubAdapter",
    "NullScreenshotAdapter",
    "NullWorkflowAdapter",
    "ScreenshotAdapter",
    "WorkflowAdapter",
    "WorkflowError",
    "get_cloudflare_adapter",
    "get_github_adapter",
    "get_screenshot_adapter",
    "get_workflow_adapter",
]
