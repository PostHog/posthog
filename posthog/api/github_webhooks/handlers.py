from typing import Any

from django.http import HttpRequest, HttpResponse

from posthog.api.github_webhooks.dispatch import GithubWebhookHandler


def _dispatch_conversations_event(
    request: HttpRequest, event_type: str, payload: dict[str, Any], delivery_id: str
) -> HttpResponse:
    from products.conversations.backend.api.github_events import (
        dispatch_github_event,  # noqa: PLC0415 - keep product dependencies off the URL import path
    )

    return dispatch_github_event(request, event_type, payload)


def _dispatch_pull_request_event(
    request: HttpRequest, event_type: str, payload: dict[str, Any], delivery_id: str
) -> HttpResponse:
    from products.tasks.backend.facade.webhooks import (
        handle_pull_request_event,  # noqa: PLC0415 - keep product dependencies off the URL import path
    )

    return handle_pull_request_event(payload)


def _dispatch_pull_request_review_event(
    request: HttpRequest, event_type: str, payload: dict[str, Any], delivery_id: str
) -> HttpResponse:
    from products.tasks.backend.facade.webhooks import (
        handle_pull_request_review_event,  # noqa: PLC0415 - keep product dependencies off the URL import path
    )

    return handle_pull_request_review_event(payload)


def _dispatch_installation_event(
    request: HttpRequest, event_type: str, payload: dict[str, Any], delivery_id: str
) -> HttpResponse:
    from posthog.api.github_callback.installation_events import (
        handle_installation_event,  # noqa: PLC0415 - keep product dependencies off the URL import path
    )

    return handle_installation_event(payload)


def _dispatch_installation_repositories_event(
    request: HttpRequest, event_type: str, payload: dict[str, Any], delivery_id: str
) -> HttpResponse:
    from posthog.api.github_callback.installation_events import (
        handle_installation_repositories_event,  # noqa: PLC0415 - keep product dependencies off the URL import path
    )

    return handle_installation_repositories_event(payload)


def _dispatch_loop_triggers(request: HttpRequest, event_type: str, payload: dict[str, Any], delivery_id: str) -> None:
    from products.tasks.backend.facade.webhooks import (
        handle_github_event_for_loops,  # noqa: PLC0415 - keep product dependencies off the URL import path
    )

    handle_github_event_for_loops(event_type, payload, delivery_id)
    return None


def _dispatch_workflow_triggers(
    request: HttpRequest, event_type: str, payload: dict[str, Any], delivery_id: str
) -> None:
    from products.workflows.backend.github_workflow_events import (
        emit_github_event,  # noqa: PLC0415 - keep product dependencies off the URL import path
    )

    emit_github_event(event_type, payload, delivery_id)
    return None


# event_type -> ordered list of (handler_name, handler). Order matters only in that
# the first handler in a bucket to return a non-None HttpResponse determines the
# response sent back to GitHub; the pre-existing single handler in each bucket keeps
# that slot so its response is unchanged by additive handlers registered after it.
GITHUB_WEBHOOK_HANDLERS: dict[str, list[tuple[str, GithubWebhookHandler]]] = {
    "issues": [
        ("conversations", _dispatch_conversations_event),
        ("loops", _dispatch_loop_triggers),
        ("workflows", _dispatch_workflow_triggers),
    ],
    "issue_comment": [
        ("conversations", _dispatch_conversations_event),
        ("loops", _dispatch_loop_triggers),
        ("workflows", _dispatch_workflow_triggers),
    ],
    "pull_request": [
        ("tasks_pr_backstop", _dispatch_pull_request_event),
        ("loops", _dispatch_loop_triggers),
        ("workflows", _dispatch_workflow_triggers),
    ],
    "pull_request_review": [
        ("tasks_pr_review", _dispatch_pull_request_review_event),
        ("workflows", _dispatch_workflow_triggers),
    ],
    "installation": [
        ("installation_lifecycle", _dispatch_installation_event),
    ],
    "installation_repositories": [
        ("installation_repositories", _dispatch_installation_repositories_event),
    ],
    "push": [
        ("loops", _dispatch_loop_triggers),
        ("workflows", _dispatch_workflow_triggers),
    ],
}
