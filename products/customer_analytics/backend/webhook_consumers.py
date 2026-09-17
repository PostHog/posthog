from collections.abc import Mapping
from datetime import datetime

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _run_github_issue_delivery(delivery: WebhookDelivery) -> None:
    payload = delivery.payload
    if not isinstance(payload, Mapping) or payload.get("action") not in {"opened", "closed", "reopened", "edited"}:
        return
    issue = payload.get("issue")
    repository = payload.get("repository")
    installation = payload.get("installation")
    if not isinstance(issue, Mapping) or not isinstance(repository, Mapping) or not isinstance(installation, Mapping):
        return
    if (
        issue.get("pull_request")
        or type(issue.get("number")) is not int
        or not isinstance(issue.get("updated_at"), str)
    ):
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
        return
    try:
        updated_at = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
    except ValueError:
        return
    if updated_at.tzinfo is None:
        return
    from products.customer_analytics.backend.facade import (
        api,  # noqa: PLC0415 - keep task registration off the ingress import path
    )

    api.process_feature_request_github_delivery(
        installation_id=str(installation_id),
        repository=full_name.lower(),
        issue_number=issue["number"],
        issue_title=issue["title"] if isinstance(issue.get("title"), str) else "",
        issue_state=state,
        issue_state_reason=issue["state_reason"] if isinstance(issue.get("state_reason"), str) else "",
        github_updated_at=updated_at,
    )


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="customer_analytics_feature_requests",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues"}),
        handler=_run_github_issue_delivery,
    ),
)
