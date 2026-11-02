import re
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet

import requests
import structlog

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationKind, IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models.integration import (
    GitHubIntegration,
    GitHubIntegrationError,
    GitLabIntegration,
    GitLabIntegrationError,
    JiraIntegration,
    LinearIntegration,
    is_supported_external_issue_provider,
)

from products.conversations.backend.models import Ticket, TicketExternalReference

logger = structlog.get_logger(__name__)

_EXTERNAL_ISSUE_INTEGRATIONS = IntegrationManager.kinds(
    IntegrationKind.GITHUB, IntegrationKind.GITLAB, IntegrationKind.LINEAR, IntegrationKind.JIRA
)


class TicketExternalReferenceValidationError(Exception):
    pass


EXTERNAL_REFERENCE_REQUIRED_CONFIG_FIELDS = {
    IntegrationKind.GITHUB.value: ("repository", "title", "body"),
    IntegrationKind.GITLAB.value: ("title", "body"),
    IntegrationKind.LINEAR.value: ("team_id", "title", "description"),
    IntegrationKind.JIRA.value: ("project_key", "title", "description"),
}

EXTERNAL_REFERENCE_NON_BLANK_CONFIG_FIELDS = {
    IntegrationKind.GITHUB.value: ("repository", "title"),
    IntegrationKind.GITLAB.value: ("title",),
    IntegrationKind.LINEAR.value: ("team_id", "title"),
    IntegrationKind.JIRA.value: ("project_key", "title"),
}

LINK_EXISTING_REQUIRED_CONTEXT_FIELDS: dict[str, dict[str, type]] = {
    IntegrationKind.GITHUB.value: {"repository": str, "number": int},
    IntegrationKind.GITLAB.value: {"issue_id": int},
    IntegrationKind.LINEAR.value: {"id": str},
    IntegrationKind.JIRA.value: {"key": str},
}


def _validate_github_assignee(integration: IntegrationRecord, repository: str, login: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", login):
        raise TicketExternalReferenceValidationError("GitHub assignee must be a GitHub login.")
    result = GitHubIntegration(integration, source="conversations", priority=Priority.CRITICAL).is_assignable(
        repository.strip(), login
    )
    if not result.get("success"):
        raise TicketExternalReferenceValidationError(
            f"Could not check whether {login} can be assigned issues in {repository.strip()}. "
            "Try again, or create the issue without an assignee."
        )
    if not result.get("assignable"):
        raise TicketExternalReferenceValidationError(
            f"GitHub user {login} cannot be assigned issues in {repository.strip()}."
        )


def _validate_external_reference_config(integration: IntegrationRecord, config: Any) -> None:
    if not isinstance(config, dict):
        raise TicketExternalReferenceValidationError("External reference config must be an object.")

    required_fields = EXTERNAL_REFERENCE_REQUIRED_CONFIG_FIELDS.get(integration.kind)
    if required_fields is None:
        raise TicketExternalReferenceValidationError("Provider not supported")

    missing_fields = [field for field in required_fields if field not in config]
    if missing_fields:
        raise TicketExternalReferenceValidationError(
            f"Missing required config fields for {integration.kind}: {', '.join(missing_fields)}."
        )

    non_string_fields = [field for field in required_fields if not isinstance(config[field], str)]
    if non_string_fields:
        raise TicketExternalReferenceValidationError(
            f"Config fields for {integration.kind} must be strings: {', '.join(non_string_fields)}."
        )

    blank_fields = [
        field for field in EXTERNAL_REFERENCE_NON_BLANK_CONFIG_FIELDS[integration.kind] if not config[field].strip()
    ]
    if blank_fields:
        raise TicketExternalReferenceValidationError(
            f"Config fields for {integration.kind} cannot be blank: {', '.join(blank_fields)}."
        )

    assignee = config.get("assignee")
    if assignee is not None and not isinstance(assignee, str):
        raise TicketExternalReferenceValidationError(f"Config field assignee for {integration.kind} must be a string.")
    if (
        assignee
        and assignee.strip()
        and integration.kind == IntegrationKind.GITLAB
        and not re.fullmatch(r"[0-9]{1,20}", assignee.strip())
    ):
        raise TicketExternalReferenceValidationError("GitLab assignee must be a numeric user ID.")

    if assignee and assignee.strip() and integration.kind == IntegrationKind.GITHUB:
        _validate_github_assignee(integration, config["repository"], assignee.strip())

    if integration.kind == IntegrationKind.LINEAR:
        team_id = config["team_id"]
        teams = LinearIntegration(integration).list_teams() or []
        valid_team_ids = {str(team["id"]) for team in teams if isinstance(team, dict) and team.get("id")}
        if team_id not in valid_team_ids:
            raise TicketExternalReferenceValidationError(
                "Invalid Linear team_id. Use integrations-linear-teams-retrieve to choose a team from this integration."
            )


def _clean_existing_external_context(integration: IntegrationRecord, external_context: Any) -> dict[str, Any]:
    if not isinstance(external_context, dict):
        raise TicketExternalReferenceValidationError("External context must be an object.")

    required_fields = LINK_EXISTING_REQUIRED_CONTEXT_FIELDS.get(integration.kind)
    if required_fields is None:
        raise TicketExternalReferenceValidationError("Provider not supported")

    error = TicketExternalReferenceValidationError(
        f"Missing required external context fields for {integration.kind}: {', '.join(required_fields)}."
    )

    cleaned: dict[str, Any] = {}
    for field, expected_type in required_fields.items():
        value = external_context.get(field)
        if isinstance(value, str):
            value = value.strip()
        if expected_type is int:
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value):
                value = int(value)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise error
        elif not isinstance(value, str) or not re.fullmatch(r"(?!\.+$)[A-Za-z0-9._-]+", value):
            raise error
        cleaned[field] = value

    title = external_context.get("title")
    if title is not None:
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 500:
            raise TicketExternalReferenceValidationError(
                "External reference title must be a non-blank string with at most 500 characters."
            )
        cleaned["title"] = title.strip()

    if integration.kind == IntegrationKind.GITHUB:
        resource_type = external_context.get("resource_type")
        if resource_type is not None:
            if resource_type not in {"issue", "pull_request"}:
                raise TicketExternalReferenceValidationError(
                    "GitHub references must identify either an issue or a pull request."
                )
            cleaned["resource_type"] = resource_type

    return cleaned


def list_external_references(team_id: int, ticket_id: UUID | None = None) -> QuerySet[TicketExternalReference]:
    qs = TicketExternalReference.objects.select_related("integration", "ticket").filter(ticket__team_id=team_id)
    if ticket_id is not None:
        qs = qs.filter(ticket_id=ticket_id)
    return qs


def get_external_reference(reference_id: UUID, team_id: int) -> TicketExternalReference | None:
    return list_external_references(team_id=team_id).filter(id=reference_id).first()


def _get_integration(team_id: int, integration_id: int) -> IntegrationRecord:
    try:
        return _EXTERNAL_ISSUE_INTEGRATIONS.get(team_id, integration_id)
    except IntegrationNotFound:
        pass
    try:
        integration = IntegrationManager.any.get(team_id, integration_id)
    except IntegrationNotFound:
        raise TicketExternalReferenceValidationError("Integration does not belong to this team.")
    if is_supported_external_issue_provider(integration.kind):
        raise TicketExternalReferenceValidationError("Integration does not belong to this team.")
    return integration


def _get_ticket_and_integration(
    team_id: int, ticket_id: UUID, integration_id: int
) -> tuple[Ticket, IntegrationRecord]:
    ticket = Ticket.objects.filter(id=ticket_id, team_id=team_id).first()
    if ticket is None:
        raise TicketExternalReferenceValidationError("Ticket does not belong to this team.")

    return ticket, _get_integration(team_id, integration_id)


def create_external_reference(
    *,
    team_id: int,
    ticket_id: UUID,
    integration_id: int,
    config: dict[str, Any] | None = None,
    external_context: dict[str, Any] | None = None,
    created_by: Any = None,
) -> tuple[TicketExternalReference, bool]:
    """Link a support ticket to an external provider issue (GitHub, GitLab, Linear, Jira).

    Pass config to create a new issue, or external_context to link an existing issue.
    """
    if (config is None) == (external_context is None):
        raise TicketExternalReferenceValidationError(
            "Provide either config (to create a new issue) or external_context (to link an existing one)."
        )

    ticket, integration = _get_ticket_and_integration(team_id, ticket_id, integration_id)

    if external_context is not None:
        if not is_supported_external_issue_provider(integration.kind):
            raise TicketExternalReferenceValidationError("Provider not supported")
        stored_context = _clean_existing_external_context(integration, external_context)
        identifier_context = {
            field: stored_context[field] for field in LINK_EXISTING_REQUIRED_CONTEXT_FIELDS[integration.kind]
        }
        existing = TicketExternalReference.objects.filter(
            ticket=ticket, integration_id=integration.id, external_context__contains=identifier_context
        ).first()
        if existing is not None:
            updated_context = {
                **(existing.external_context or {}),
                **{key: stored_context[key] for key in ("title", "resource_type") if key in stored_context},
            }
            if updated_context != existing.external_context:
                existing.external_context = updated_context
                existing.save(update_fields=["external_context"])
            return existing, False

        return TicketExternalReference.objects.create(
            ticket=ticket,
            integration_id=integration.id,
            external_context=stored_context,
            created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
        ), True

    _validate_external_reference_config(integration, config)
    provider_config = dict(config or {})
    title = provider_config["title"].strip()
    provider_config["title"] = title
    assignee = (provider_config.pop("assignee", None) or "").strip()
    if assignee:
        provider_config["assignee"] = assignee

    # Append backlink to the support ticket in the body if not already present
    ticket_url = f"{settings.SITE_URL.rstrip('/')}/project/{team_id}/support/tickets/{ticket.id}"
    backlink_note = f"\n\n---\n*Linked PostHog Support Ticket #{ticket.ticket_number}: {ticket_url}*"
    body_key = "description" if integration.kind in (IntegrationKind.LINEAR, IntegrationKind.JIRA) else "body"
    if backlink_note not in provider_config.get(body_key, ""):
        provider_config[body_key] = (provider_config.get(body_key, "") + backlink_note).strip()

    if integration.kind == IntegrationKind.GITHUB:
        created_context = GitHubIntegration(
            integration, source="conversations", priority=Priority.CRITICAL
        ).create_issue(provider_config)
    elif integration.kind == IntegrationKind.GITLAB:
        created_context = GitLabIntegration(integration).create_issue(provider_config)
    elif integration.kind == IntegrationKind.LINEAR:
        created_context = LinearIntegration(integration).create_issue(ticket_url, provider_config)
    elif integration.kind == IntegrationKind.JIRA:
        created_context = JiraIntegration(integration).create_issue(provider_config)
    else:
        raise TicketExternalReferenceValidationError("Provider not supported")

    created_context["title"] = title
    return TicketExternalReference.objects.create(
        ticket=ticket,
        integration_id=integration.id,
        external_context=created_context,
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
    ), True


def delete_external_reference(*, team_id: int, reference_id: UUID) -> bool:
    ref = get_external_reference(reference_id=reference_id, team_id=team_id)
    if ref is None:
        return False
    ref.delete()
    return True


def search_external_issues(
    *,
    team_id: int,
    integration_id: int,
    search: str,
    repository: str | None = None,
) -> list[dict[str, Any]]:
    integration = _get_integration(team_id, integration_id)

    try:
        if integration.kind == IntegrationKind.GITHUB:
            if not repository:
                raise TicketExternalReferenceValidationError("A repository is required to search GitHub issues.")
            if "/" in repository:
                raise TicketExternalReferenceValidationError(
                    "Pass the repository name without an owner; only the integration's account can be searched."
                )
            return GitHubIntegration(integration, source="conversations", priority=Priority.CRITICAL).search_issues(
                repository, search
            )
        elif integration.kind == IntegrationKind.GITLAB:
            return GitLabIntegration(integration).search_issues(search)
        elif integration.kind == IntegrationKind.LINEAR:
            return LinearIntegration(integration).search_issues(search)
        elif integration.kind == IntegrationKind.JIRA:
            return JiraIntegration(integration).search_issues(search)
    except (GitHubIntegrationError, GitLabIntegrationError, requests.RequestException, ValueError) as error:
        raise TicketExternalReferenceValidationError(f"Failed to search {integration.kind} issues.") from error

    raise TicketExternalReferenceValidationError("Provider not supported")
