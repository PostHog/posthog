"""Connect-time GitHub installation facts projected onto the PostHog organization group.

Whether a GitHub App is installed on an organization or a personal account, and the shape of
the installation, are durable facts known when the installation is connected. Projecting them
as organization group properties makes them usable for segmentation without joining through
events.
"""

from typing import Any

import posthoganalytics

from posthog.exceptions_capture import capture_exception

ORGANIZATION_GROUP_TYPE = "organization"

GITHUB_ACCOUNT_TYPE_PROPERTY = "github_account_type"
GITHUB_REPOSITORY_SELECTION_PROPERTY = "github_repository_selection"
GITHUB_REPOSITORY_COUNT_PROPERTY = "github_repository_count"


def normalize_github_account_type(owner_type: str | None) -> str | None:
    """Map GitHub's account ``type`` ("Organization" / "User") to org vs personal."""
    if owner_type == "Organization":
        return "organization"
    if owner_type == "User":
        return "personal"
    return None


def github_organization_group_properties(
    *,
    account_type: str | None,
    repository_selection: str | None = None,
    repository_count: int | None = None,
) -> dict[str, Any]:
    """Group properties for the connect-time GitHub facts, omitting unknown values."""
    properties: dict[str, Any] = {}
    if account_type is not None:
        properties[GITHUB_ACCOUNT_TYPE_PROPERTY] = account_type
    if repository_selection is not None:
        properties[GITHUB_REPOSITORY_SELECTION_PROPERTY] = repository_selection
    if repository_count is not None:
        properties[GITHUB_REPOSITORY_COUNT_PROPERTY] = repository_count
    return properties


def project_github_metadata_onto_organization(
    *,
    organization_id: str,
    account_type: str | None,
    repository_selection: str | None = None,
    repository_count: int | None = None,
) -> bool:
    """Best-effort ``group_identify`` of the connect-time GitHub facts. Never raises.

    Returns whether a ``group_identify`` was issued (i.e. at least one property was known).
    ``account_type`` must already be normalized via :func:`normalize_github_account_type`.
    """
    properties = github_organization_group_properties(
        account_type=account_type,
        repository_selection=repository_selection,
        repository_count=repository_count,
    )
    if not properties:
        return False
    try:
        posthoganalytics.group_identify(ORGANIZATION_GROUP_TYPE, str(organization_id), properties=properties)
    except Exception as e:
        capture_exception(e)
        return False
    return True
