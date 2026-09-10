"""URLs for issues created in an external tracker through an Integration."""

from typing import Any

from . import model
from .github import GitHubIntegration
from .gitlab import GitLabIntegration
from .jira import JiraIntegration
from .linear import LinearIntegration

SUPPORTED_EXTERNAL_ISSUE_PROVIDERS = frozenset(
    {
        model.Integration.IntegrationKind.LINEAR,
        model.Integration.IntegrationKind.GITHUB,
        model.Integration.IntegrationKind.GITLAB,
        model.Integration.IntegrationKind.JIRA,
    }
)


def is_supported_external_issue_provider(kind: str) -> bool:
    return kind in SUPPORTED_EXTERNAL_ISSUE_PROVIDERS


def external_issue_url(integration: model.Integration, external_context: dict[str, Any] | None) -> str:
    """Link to an external issue from the identifier its integration client stored.

    Returns an empty string when the context does not carry the provider's identifier, so a
    half-written reference renders as "no link" rather than a URL that goes nowhere.
    """
    context = external_context or {}

    if integration.kind == model.Integration.IntegrationKind.LINEAR:
        issue_id = context.get("id")
        if not issue_id:
            return ""
        url_key = LinearIntegration(integration).url_key()
        return f"https://linear.app/{url_key}/issue/{issue_id}"

    if integration.kind == model.Integration.IntegrationKind.GITHUB:
        repository = context.get("repository")
        number = context.get("number")
        if not repository or not number:
            return ""
        org = GitHubIntegration(integration).organization()
        return f"https://github.com/{org}/{repository}/issues/{number}"

    if integration.kind == model.Integration.IntegrationKind.GITLAB:
        issue_id = context.get("issue_id")
        if not issue_id:
            return ""
        gitlab = GitLabIntegration(integration)
        return f"{gitlab.hostname}/{gitlab.project_path}/issues/{issue_id}"

    if integration.kind == model.Integration.IntegrationKind.JIRA:
        issue_key = context.get("key")
        if not issue_key:
            return ""
        return f"{JiraIntegration(integration).site_url()}/browse/{issue_key}"

    return ""
