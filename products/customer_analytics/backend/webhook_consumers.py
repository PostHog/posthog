from collections.abc import Mapping
from datetime import UTC, datetime

import structlog
from structlog.contextvars import bound_contextvars

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery

logger = structlog.get_logger(__name__)


def _log_ignored_delivery(reason: str) -> None:
    logger.debug("feature_request_github_delivery_ignored", reason=reason)


def _process_github_issue_delivery(delivery: WebhookDelivery) -> None:
    payload: object = delivery.payload
    if not isinstance(payload, Mapping):
        _log_ignored_delivery("invalid_payload")
        return
    if payload.get("action") not in {"opened", "closed", "reopened", "edited"}:
        _log_ignored_delivery("unsupported_action")
        return

    issue = payload.get("issue")
    repository = payload.get("repository")
    installation = payload.get("installation")
    if not isinstance(issue, Mapping) or not isinstance(repository, Mapping) or not isinstance(installation, Mapping):
        _log_ignored_delivery("missing_issue_context")
        return
    if issue.get("pull_request"):
        _log_ignored_delivery("pull_request")
        return
    if type(issue.get("number")) is not int or not isinstance(issue.get("updated_at"), str):
        _log_ignored_delivery("invalid_issue")
        return

    full_name = repository.get("full_name")
    installation_id = installation.get("id")
    state = issue.get("state")
    if (
        not isinstance(full_name, str)
        or type(installation_id) is not int
        or state not in {"open", "closed"}
        or (state == "closed" and issue.get("state_reason") not in {None, "", "completed", "not_planned"})
    ):
        _log_ignored_delivery("unsupported_issue_state")
        return
    try:
        updated_at = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
    except ValueError:
        _log_ignored_delivery("invalid_updated_at")
        return
    if updated_at.tzinfo is None:
        _log_ignored_delivery("invalid_updated_at")
        return

    github_received_at = delivery.received_at.astimezone(UTC).isoformat()
    from products.customer_analytics.backend.facade import (
        api,  # noqa: PLC0415 - keep task registration off the ingress import path
    )

    task_id = api.process_feature_request_github_delivery(
        installation_id=str(installation_id),
        repository=full_name.lower(),
        issue_number=issue["number"],
        issue_title=issue["title"] if isinstance(issue.get("title"), str) else "",
        issue_state=state,
        issue_state_reason=issue["state_reason"] if isinstance(issue.get("state_reason"), str) else "",
        github_updated_at=updated_at,
        github_delivery_id=delivery.delivery_id,
        github_received_at=github_received_at,
    )
    with bound_contextvars(
        github_delivery_id=delivery.delivery_id,
        task_id=task_id,
        sync_attempt=0,
        installation_id=str(installation_id),
        github_received_at=github_received_at,
    ):
        logger.info("feature_request_github_delivery_queued")


def _run_github_issue_delivery(delivery: WebhookDelivery) -> None:
    with bound_contextvars(
        github_delivery_id=delivery.delivery_id,
        github_received_at=delivery.received_at.astimezone(UTC).isoformat(),
    ):
        _process_github_issue_delivery(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="customer_analytics_feature_requests",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues"}),
        handler=_run_github_issue_delivery,
    ),
)
