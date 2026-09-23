import re
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import requests
import structlog
from structlog.contextvars import bound_contextvars, get_contextvars

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models import Integration
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration.github import GitHubIntegration
from posthog.permissions import posthog_feature_flag_enabled

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_FEATURE_REQUESTS_FLAG
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic.feature_requests import (
    FeatureRequestConflictError,
    FeatureRequestValidationError,
    _ensure_initial_history,
    _get_accessible_feature_request_for_update,
    _refresh_feature_request,
)
from products.customer_analytics.backend.models import (
    FeatureRequest,
    FeatureRequestGitHubLink,
    FeatureRequestHistory,
    FeatureRequestHistorySource,
    FeatureRequestStatus,
)

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class GitHubLinkUnavailableError(ValueError):
    pass


@frozen
class GitHubIssueState:
    title: str
    state: Literal["open", "closed"]
    reason: str
    updated_at: datetime


logger = structlog.get_logger(__name__)

_CONFLICT_MESSAGE = "This request changed since you opened it. Reload it and try again."
_REPOSITORY = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+")


def _log_manual_action_after_commit(
    *,
    action: str,
    team_id: int,
    feature_request_id: UUID,
    github_link_id: UUID | None,
    integration_id: int | None,
    changed: bool,
) -> None:
    with bound_contextvars(
        team_id=team_id,
        feature_request_id=str(feature_request_id),
        github_link_id=str(github_link_id) if github_link_id is not None else None,
        integration_id=integration_id,
        action=action,
    ):
        committed_context = get_contextvars()
    transaction.on_commit(
        partial(logger.info, "feature_request_github_manual_action_committed", changed=changed, **committed_context)
    )


def _log_issue_fetch_failure(
    integration: Integration, *, stage: str, error_type: str, status_code: int | None = None
) -> None:
    logger.warning(
        "feature_request_github_issue_fetch_failed",
        team_id=integration.team_id,
        integration_id=integration.id,
        stage=stage,
        error_type=error_type,
        status_code=status_code,
    )


def _parse_issue_url(issue_url: str) -> tuple[str, int]:
    try:
        parsed = urlparse(issue_url)
        port = parsed.port
    except ValueError as exc:
        raise FeatureRequestValidationError("issue_url", "Enter a GitHub issue URL.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
    ):
        raise FeatureRequestValidationError("issue_url", "Enter a GitHub issue URL.")
    match = re.fullmatch(r"/([^/]+/[^/]+)/issues/([0-9]+)/?", parsed.path)
    if match is None or not _REPOSITORY.fullmatch(match[1]) or match[1].split("/")[1] in {".", ".."}:
        raise FeatureRequestValidationError("issue_url", "Enter a GitHub issue URL. Pull requests are not supported.")
    number = int(match[2])
    if not 0 < number <= 2147483647:
        raise FeatureRequestValidationError("issue_url", "Enter a valid GitHub issue number.")
    return match[1].lower(), number


def _issue_snapshot(link: FeatureRequestGitHubLink) -> dict[str, object]:
    return {
        "id": str(link.id),
        "issue_url": f"https://github.com/{link.repository}/issues/{link.issue_number}",
        "repository": link.repository,
        "issue_number": link.issue_number,
        "issue_title": link.issue_title,
        "issue_state": link.issue_state,
        "sync_enabled": link.sync_enabled,
    }


def _github_status(reason: str) -> str:
    if reason in {"completed", ""}:
        return FeatureRequestStatus.COMPLETED
    if reason == "not_planned":
        return FeatureRequestStatus.WONT_FIX
    raise GitHubLinkUnavailableError("GitHub returned an unsupported closure reason. Check the issue and try again.")


def _parse_issue_payload(payload: dict[str, object], repository: str, issue_number: int) -> GitHubIssueState:
    html_url = payload.get("html_url")
    repository_url = payload.get("repository_url")
    if not isinstance(html_url, str) or not isinstance(repository_url, str):
        raise GitHubLinkUnavailableError("GitHub returned an invalid issue. Try again.")
    try:
        coordinates = _parse_issue_url(html_url)
    except FeatureRequestValidationError as exc:
        raise GitHubLinkUnavailableError("GitHub returned an invalid issue. Try again.") from exc
    if (
        "pull_request" in payload
        or type(payload.get("number")) is not int
        or payload["number"] != issue_number
        or coordinates != (repository, issue_number)
        or repository_url.lower() != f"https://api.github.com/repos/{repository}"
    ):
        raise GitHubLinkUnavailableError("GitHub returned a different issue. Check the URL and try again.")
    state = payload.get("state")
    title = payload.get("title")
    timestamp = payload.get("updated_at")
    reason = payload.get("state_reason") or ""
    if state not in {"open", "closed"} or not isinstance(title, str) or not isinstance(reason, str):
        raise GitHubLinkUnavailableError("GitHub returned an invalid issue state. Try again.")
    if state == "closed":
        _github_status(reason)
    try:
        updated_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00")) if isinstance(timestamp, str) else None
    except ValueError as exc:
        raise GitHubLinkUnavailableError("GitHub returned an invalid issue update time. Try again.") from exc
    if updated_at is None or timezone.is_naive(updated_at):
        raise GitHubLinkUnavailableError("GitHub returned an invalid issue update time. Try again.")
    return GitHubIssueState(
        title=title, state="closed" if state == "closed" else "open", reason=reason, updated_at=updated_at
    )


def _integration(
    team_id: int,
    integration_id: int | None,
    installation_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> Integration:
    if integration_id is None:
        raise FeatureRequestValidationError("integration_id", "Reconnect the GitHub integration before resuming sync.")
    integration = Integration.objects.filter(id=integration_id, team_id=team_id, kind="github").first()
    if (
        integration is None
        or not integration.integration_id
        or (installation_id is not None and integration.integration_id != installation_id)
        or GitHubIntegration(integration).installation_unavailable()
    ):
        raise FeatureRequestValidationError(
            "integration_id", "Select an available GitHub integration for this project."
        )
    if user_access_control is not None and not user_access_control.check_access_level_for_object(
        integration, required_level="viewer"
    ):
        raise FeatureRequestValidationError("integration_id", "Select a GitHub integration you can access.")
    return integration


def _fetch_issue(
    integration: Integration, repository: str, issue_number: int, *, priority: Priority = Priority.NORMAL
) -> GitHubIssueState:
    try:
        response = GitHubIntegration(integration, source="customer_analytics", priority=priority).api_request(
            "GET",
            f"/repos/{repository}/issues/{issue_number}",
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}",
            priority=priority,
            retry_transient=False,
        )
    except GitHubEgressBudgetExhausted as exc:
        _log_issue_fetch_failure(integration, stage="budget", error_type=type(exc).__name__)
        raise GitHubLinkUnavailableError("GitHub could not load this issue. Try again.") from exc
    except GitHubRateLimitError as exc:
        _log_issue_fetch_failure(integration, stage="rate_limit", error_type=type(exc).__name__)
        raise GitHubLinkUnavailableError("GitHub could not load this issue. Try again.") from exc
    except GitHubIntegrationError as exc:
        _log_issue_fetch_failure(integration, stage="integration", error_type=type(exc).__name__)
        raise GitHubLinkUnavailableError("GitHub could not load this issue. Try again.") from exc
    except requests.RequestException as exc:
        _log_issue_fetch_failure(integration, stage="transport", error_type=type(exc).__name__)
        raise
    if response.status_code in {401, 403, 404}:
        _log_issue_fetch_failure(
            integration, stage="status", error_type="GitHubResponseError", status_code=response.status_code
        )
        raise FeatureRequestValidationError(
            "issue_url", "GitHub cannot access this issue. Check the integration's repository access."
        )
    if response.status_code != 200:
        _log_issue_fetch_failure(
            integration, stage="status", error_type="GitHubResponseError", status_code=response.status_code
        )
        raise GitHubLinkUnavailableError("GitHub could not load this issue. Try again.")
    try:
        payload = response.json()
    except ValueError as exc:
        _log_issue_fetch_failure(integration, stage="invalid_payload", error_type=type(exc).__name__, status_code=200)
        raise GitHubLinkUnavailableError("GitHub returned an invalid issue. Try again.") from exc
    if not isinstance(payload, dict):
        _log_issue_fetch_failure(integration, stage="invalid_payload", error_type="InvalidPayload", status_code=200)
        raise GitHubLinkUnavailableError("GitHub returned an invalid issue. Try again.")
    try:
        return _parse_issue_payload(payload, repository, issue_number)
    except GitHubLinkUnavailableError as exc:
        _log_issue_fetch_failure(integration, stage="invalid_payload", error_type=type(exc).__name__, status_code=200)
        raise


def _editable_request(
    team_id: int, request_id: UUID, expected_version: int, user_access_control: "UserAccessControl"
) -> FeatureRequest | None:
    request = _get_accessible_feature_request_for_update(
        team_id=team_id, feature_request_id=request_id, user_access_control=user_access_control
    )
    if request is not None:
        if request.archived_at is not None:
            raise FeatureRequestValidationError("feature_request", "Restore this request before changing GitHub sync.")
        if request.version != expected_version:
            raise FeatureRequestConflictError(_CONFLICT_MESSAGE)
    return request


def _apply_state(
    request: FeatureRequest, link: FeatureRequestGitHubLink, issue: GitHubIssueState
) -> list[contracts.FeatureRequestHistoryChange]:
    before = request.status
    if issue.state == "closed":
        if link.status_before_github_close is None:
            link.status_before_github_close = before
        request.status = _github_status(issue.reason)
    elif link.status_before_github_close is not None:
        request.status = link.status_before_github_close
        link.status_before_github_close = None
    link.issue_title = issue.title
    link.issue_state = issue.state
    link.issue_state_reason = issue.reason
    link.github_updated_at = issue.updated_at
    link.last_synced_at = timezone.now()
    link.save()
    return [{"field": "status", "before": before, "after": request.status}] if request.status != before else []


def _save_change(
    request: FeatureRequest, changes: list[contracts.FeatureRequestHistoryChange], actor_id: int | None
) -> None:
    request.version += 1
    request.updated_at = timezone.now()
    request.updated_by_id = actor_id
    request.save(update_fields=["status", "version", "updated_at", "updated_by_id"])
    if changes:
        FeatureRequestHistory.objects.for_team(request.team_id).create(
            team_id=request.team_id,
            feature_request=request,
            changes=changes,
            source=FeatureRequestHistorySource.GITHUB,
            actor_id=actor_id,
            changed_at=request.updated_at,
        )


def link_feature_request_github(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.LinkFeatureRequestGitHubInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    repository, issue_number = _parse_issue_url(input.issue_url)
    with transaction.atomic():
        request = _editable_request(team_id, feature_request_id, input.expected_version, user_access_control)
        if request is None:
            return None
        if FeatureRequestGitHubLink.objects.for_team(team_id).filter(feature_request=request).exists():
            raise FeatureRequestValidationError(
                "issue_url", "This request already has a GitHub issue. Unlink it before adding another."
            )
    integration = _integration(team_id, input.integration_id, user_access_control=user_access_control)
    installation_id = integration.integration_id
    with bound_contextvars(
        team_id=team_id,
        feature_request_id=str(feature_request_id),
        integration_id=integration.id,
        action="link",
    ):
        issue = _fetch_issue(integration, repository, issue_number)
    with transaction.atomic():
        request = _editable_request(team_id, feature_request_id, input.expected_version, user_access_control)
        if request is None:
            return None
        integration = _integration(
            team_id, input.integration_id, installation_id, user_access_control=user_access_control
        )
        if FeatureRequestGitHubLink.objects.for_team(team_id).filter(feature_request=request).exists():
            raise FeatureRequestConflictError(_CONFLICT_MESSAGE)
        _ensure_initial_history(request)
        link = FeatureRequestGitHubLink.objects.for_team(team_id).create(
            team_id=team_id,
            feature_request=request,
            integration=integration,
            installation_id=installation_id,
            repository=repository,
            issue_number=issue_number,
            sync_enabled_by_id=actor_id,
        )
        changes = _apply_state(request, link, issue)
        changes.insert(0, {"field": "github_link", "before": None, "after": _issue_snapshot(link)})
        _save_change(request, changes, actor_id)
        _log_manual_action_after_commit(
            action="link",
            team_id=team_id,
            feature_request_id=feature_request_id,
            github_link_id=link.id,
            integration_id=integration.id,
            changed=True,
        )
    return _refresh_feature_request(
        team_id=team_id, feature_request_id=feature_request_id, user_access_control=user_access_control
    )


def set_feature_request_github_sync(
    *,
    team_id: int,
    feature_request_id: UUID,
    expected_version: int,
    enabled: bool,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    with transaction.atomic():
        request = _editable_request(team_id, feature_request_id, expected_version, user_access_control)
        if request is None:
            return None
        link = FeatureRequestGitHubLink.objects.for_team(team_id).filter(feature_request=request).first()
        if link is None:
            raise FeatureRequestValidationError("github_link", "Link a GitHub issue first.")
        if not enabled:
            changed = link.sync_enabled
            if changed:
                _ensure_initial_history(request)
                link.sync_enabled = False
                link.save(update_fields=["sync_enabled"])
                _save_change(request, [{"field": "github_sync", "before": True, "after": False}], actor_id)
            _log_manual_action_after_commit(
                action="pause",
                team_id=team_id,
                feature_request_id=feature_request_id,
                github_link_id=link.id,
                integration_id=link.integration_id,
                changed=changed,
            )
            return _refresh_feature_request(
                team_id=team_id, feature_request_id=feature_request_id, user_access_control=user_access_control
            )
    integration = _integration(
        team_id, link.integration_id, link.installation_id, user_access_control=user_access_control
    )
    with bound_contextvars(
        team_id=team_id,
        feature_request_id=str(feature_request_id),
        github_link_id=str(link.id),
        integration_id=integration.id,
        action="resume",
    ):
        issue = _fetch_issue(integration, link.repository, link.issue_number)
    with transaction.atomic():
        request = _editable_request(team_id, feature_request_id, expected_version, user_access_control)
        if request is None:
            return None
        current = FeatureRequestGitHubLink.objects.for_team(team_id).select_for_update().filter(id=link.id).first()
        if current is None or current.integration_id != link.integration_id:
            raise FeatureRequestConflictError(_CONFLICT_MESSAGE)
        _integration(team_id, current.integration_id, current.installation_id, user_access_control=user_access_control)
        if current.github_updated_at is not None and issue.updated_at < current.github_updated_at:
            raise FeatureRequestConflictError(_CONFLICT_MESSAGE)
        _ensure_initial_history(request)
        changes: list[contracts.FeatureRequestHistoryChange] = []
        if not current.sync_enabled:
            changes.append({"field": "github_sync", "before": False, "after": True})
        current.sync_enabled = True
        current.sync_enabled_by_id = actor_id
        changes.extend(_apply_state(request, current, issue))
        changed = bool(changes)
        if changed:
            _save_change(request, changes, actor_id)
        _log_manual_action_after_commit(
            action="resume",
            team_id=team_id,
            feature_request_id=feature_request_id,
            github_link_id=current.id,
            integration_id=current.integration_id,
            changed=bool(changed),
        )
    return _refresh_feature_request(
        team_id=team_id, feature_request_id=feature_request_id, user_access_control=user_access_control
    )


def unlink_feature_request_github(
    *,
    team_id: int,
    feature_request_id: UUID,
    expected_version: int,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    with transaction.atomic():
        request = _editable_request(team_id, feature_request_id, expected_version, user_access_control)
        if request is None:
            return None
        link = FeatureRequestGitHubLink.objects.for_team(team_id).filter(feature_request=request).first()
        if link is not None:
            _ensure_initial_history(request)
            before = _issue_snapshot(link)
            link_id = link.id
            integration_id = link.integration_id
            link.delete()
            _save_change(request, [{"field": "github_link", "before": before, "after": None}], actor_id)
            _log_manual_action_after_commit(
                action="unlink",
                team_id=team_id,
                feature_request_id=feature_request_id,
                github_link_id=link_id,
                integration_id=integration_id,
                changed=True,
            )
    return _refresh_feature_request(
        team_id=team_id, feature_request_id=feature_request_id, user_access_control=user_access_control
    )


def _eligible_integration(link: FeatureRequestGitHubLink) -> tuple[Integration | None, str | None]:
    if not link.sync_enabled:
        return None, "paused"
    if link.feature_request.archived_at is not None:
        return None, "archived"
    if link.integration_id is None:
        return None, "unavailable"
    try:
        return _integration(link.team_id, link.integration_id, link.installation_id), None
    except FeatureRequestValidationError:
        return None, "unavailable"


def process_github_issue_update(
    *,
    installation_id: str,
    repository: str,
    issue_number: int,
    issue_title: str,
    issue_state: str,
    issue_state_reason: str,
    github_updated_at: datetime,
) -> None:
    with bound_contextvars(installation_id=installation_id):
        matched = applied = skipped = conflicted = failed = 0
        outcome = "success"
        ignored_reason: str | None = None
        error_type: str | None = None
        try:
            if issue_state not in {"open", "closed"} or timezone.is_naive(github_updated_at):
                outcome = "ignored"
                ignored_reason = "invalid_state"
                return
            if issue_state == "closed" and issue_state_reason not in {"completed", "not_planned", ""}:
                outcome = "ignored"
                ignored_reason = "unsupported_closure_reason"
                return
            issue = GitHubIssueState(
                title=issue_title,
                state="closed" if issue_state == "closed" else "open",
                reason=issue_state_reason,
                updated_at=github_updated_at,
            )
            # One installation can serve several projects; each mutation below re-enters its team's scope.
            targets = (
                FeatureRequestGitHubLink.objects.unscoped()
                .filter(
                    installation_id=installation_id,
                    repository=repository.lower(),
                    issue_number=issue_number,
                    sync_enabled=True,
                )
                .values_list("id", "team_id", "feature_request_id", "integration_id")
            )
            for link_id, team_id, feature_request_id, integration_id in targets.iterator():
                matched += 1
                with bound_contextvars(
                    team_id=team_id,
                    feature_request_id=str(feature_request_id),
                    github_link_id=str(link_id),
                    integration_id=integration_id,
                ):
                    stage = "load_target"
                    try:
                        link = (
                            FeatureRequestGitHubLink.objects.for_team(team_id)
                            .select_related("feature_request", "team", "sync_enabled_by")
                            .filter(id=link_id)
                            .first()
                        )
                        if link is None:
                            skipped += 1
                            logger.info("feature_request_github_target_skipped", reason="not_found")
                            continue
                        integration, skip_reason = _eligible_integration(link)
                        if integration is None or skip_reason is not None:
                            skipped += 1
                            logger.info("feature_request_github_target_skipped", reason=skip_reason)
                            continue
                        user = link.sync_enabled_by
                        if user is None:
                            skipped += 1
                            logger.info("feature_request_github_target_skipped", reason="user_missing")
                            continue
                        if not posthog_feature_flag_enabled(
                            CUSTOMER_ANALYTICS_FEATURE_REQUESTS_FLAG,
                            str(user.distinct_id),
                            organization_id=link.team.organization_id,
                            team_id=team_id,
                        ):
                            skipped += 1
                            logger.info("feature_request_github_target_skipped", reason="flag_disabled")
                            continue
                        if link.github_updated_at is not None and issue.updated_at < link.github_updated_at:
                            skipped += 1
                            logger.debug("feature_request_github_target_skipped", reason="stale")
                            continue
                        current_issue = issue
                        if issue.updated_at == link.github_updated_at:
                            if (issue.state, issue.reason) == (link.issue_state, link.issue_state_reason):
                                skipped += 1
                                logger.debug("feature_request_github_target_skipped", reason="duplicate")
                                continue
                            # GitHub timestamps have second precision. Resolve conflicting same-second events from the API.
                            stage = "same_second_fetch"
                            current_issue = _fetch_issue(
                                integration, link.repository, link.issue_number, priority=Priority.BATCH
                            )
                        expected_version = link.feature_request.version
                        stage = "apply"
                        with transaction.atomic():
                            request = (
                                FeatureRequest.objects.for_team(team_id)
                                .select_for_update()
                                .filter(id=link.feature_request_id)
                                .first()
                            )
                            if request is None:
                                skipped += 1
                                logger.info("feature_request_github_target_skipped", reason="not_found")
                                continue
                            current = (
                                FeatureRequestGitHubLink.objects.for_team(team_id)
                                .select_for_update()
                                .filter(id=link_id)
                                .first()
                            )
                            if current is None:
                                skipped += 1
                                logger.info("feature_request_github_target_skipped", reason="not_found")
                                continue
                            _, skip_reason = _eligible_integration(current)
                            if skip_reason is not None:
                                skipped += 1
                                logger.info("feature_request_github_target_skipped", reason=skip_reason)
                                continue
                            if request.version != expected_version:
                                conflicted += 1
                                logger.info("feature_request_github_target_conflicted", reason="version_conflict")
                                continue
                            if (
                                current.github_updated_at is not None
                                and current_issue.updated_at < current.github_updated_at
                            ):
                                skipped += 1
                                logger.debug("feature_request_github_target_skipped", reason="stale")
                                continue
                            if current_issue.updated_at == current.github_updated_at and (
                                current_issue.state,
                                current_issue.reason,
                            ) == (current.issue_state, current.issue_state_reason):
                                skipped += 1
                                logger.debug("feature_request_github_target_skipped", reason="duplicate")
                                continue
                            _ensure_initial_history(request)
                            status_before = request.status
                            changes = _apply_state(request, current, current_issue)
                            changed = bool(changes)
                            if changes:
                                _save_change(request, changes, None)
                            committed_context = get_contextvars()
                            transaction.on_commit(
                                partial(
                                    logger.info,
                                    "feature_request_github_target_applied",
                                    changed=changed,
                                    status_before=status_before,
                                    status_after=request.status,
                                    **committed_context,
                                )
                            )
                        applied += 1
                    except Exception as exc:
                        failed += 1
                        logger.error(  # noqa: TRY400 - records the error category without exception details
                            "feature_request_github_target_failed",
                            error_type=type(exc).__name__,
                            stage=stage,
                        )
                        raise
            if conflicted:
                raise FeatureRequestConflictError(_CONFLICT_MESSAGE)
        except Exception as exc:
            outcome = "failure"
            error_type = type(exc).__name__
            raise
        finally:
            log_method = logger.error if outcome == "failure" else logger.info
            log_method(
                "feature_request_github_delivery_summary",
                outcome=outcome,
                ignored_reason=ignored_reason,
                matched=matched,
                applied=applied,
                skipped=skipped,
                conflicted=conflicted,
                failed=failed,
                error_type=error_type,
            )
