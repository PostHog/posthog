"""Receiver for Linear agent (``linear-agent`` integration) webhooks.

Linear delivers events for every workspace that authorized the app to a single app-level
webhook URL (configured in the Linear app dashboard). We authenticate each delivery by HMAC
signature, map it to a PostHog team via the payload's ``organizationId``, and create a PostHog
Code task when an issue is delegated/assigned to the app's bot user.

There is no per-install webhook to register — see ``LinearAgentIntegration``.
"""

import hmac
import json
import hashlib
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration, LinearAgentIntegration
from posthog.redis import get_client

from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

# Feature-flag gate for the whole Linear agent feature (see frontend FEATURE_FLAGS).
POSTHOG_BOT_EVERYWHERE_FLAG = "posthog-bot-everywhere"

LINEAR_ISSUE_REFERENCE_KIND = "linear-issue"

# Fast-path dedup window on the per-delivery id. Covers Linear's 1-minute retry; the longer
# 1h/6h retries are caught by the logical "one task per issue" dedup instead.
_DEDUP_TTL_SECONDS = 60 * 60


def verify_linear_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Verify Linear's ``Linear-Signature`` header: hex HMAC-SHA256 of the raw request body."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _is_duplicate_delivery(delivery_id: str | None) -> bool:
    """Best-effort dedup on the ``Linear-Delivery`` id (a per-delivery UUID v4)."""
    if not delivery_id:
        return False
    try:
        client = get_client()
        # SET NX returns truthy only if the key did not already exist (first time we've seen it).
        was_set = client.set(f"linear_agent_webhook:{delivery_id}", b"1", nx=True, ex=_DEDUP_TTL_SECONDS)
        return not was_set
    except Exception:
        # A Redis hiccup must not drop a webhook — the logical dedup still prevents duplicate tasks.
        return False


def _feature_enabled(integration: Integration) -> bool:
    """Gate webhook processing behind ``POSTHOG_BOT_EVERYWHERE`` for the integration's team.

    Fails closed (returns False) while the feature is flag-gated, including on flag-service errors.
    """
    try:
        organization_id = str(integration.team.organization_id)
        project_id = str(integration.team_id)
        return bool(
            posthoganalytics.feature_enabled(
                POSTHOG_BOT_EVERYWHERE_FLAG,
                project_id,
                groups={"organization": organization_id, "project": project_id},
                group_properties={
                    "organization": {"id": organization_id},
                    "project": {"id": project_id},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("linear_agent_webhook_flag_check_failed", integration_id=integration.id)
        return False


@csrf_exempt
def handle_linear_agent_webhook(request: HttpRequest) -> HttpResponse:
    """Verify, dedup, and dispatch a Linear agent webhook delivery.

    No auth middleware — authenticity comes from the HMAC signature. Accepted and ignored events
    both return 2xx so Linear doesn't retry; only signature/config failures return 4xx/5xx.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    secret = settings.LINEAR_AGENT_WEBHOOK_SECRET
    if not secret:
        return HttpResponse("Webhook not configured", status=500)

    signature = request.headers.get("Linear-Signature")
    if not verify_linear_signature(request.body, signature, secret):
        return HttpResponse("Invalid signature", status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    if _is_duplicate_delivery(request.headers.get("Linear-Delivery")):
        return JsonResponse({"status": "duplicate"})

    try:
        _dispatch(payload)
    except Exception as e:
        # Never 5xx on a processing error: Linear would retry a poison payload for 6 hours.
        logger.exception("linear_agent_webhook_dispatch_failed")
        capture_exception(e)

    return JsonResponse({"status": "ok"})


def _dispatch(payload: dict[str, Any]) -> None:
    if payload.get("type") != "Issue":
        return  # only Issue events drive task creation in v1

    organization_id = payload.get("organizationId")
    if not organization_id:
        return

    integration = Integration.objects.filter(kind="linear-agent", integration_id=str(organization_id)).first()
    if integration is None:
        return  # no team has this Linear org connected (or it was uninstalled)

    if not _feature_enabled(integration):
        return

    if _is_assignment_to_bot(payload, integration):
        _create_task_for_issue(payload, integration)


def _is_assignment_to_bot(payload: dict[str, Any], integration: Integration) -> bool:
    """True when the event is the issue being newly delegated/assigned to our bot user."""
    bot_user_id = LinearAgentIntegration(integration).bot_user_id()
    if not bot_user_id:
        return False

    data = payload.get("data") or {}
    # Assigning an issue to an app sets it as the issue's `delegate`; fall back to `assignee`.
    new_owner = data.get("delegateId") or data.get("assigneeId")
    if new_owner != bot_user_id:
        return False

    # On updates, only fire when the owner field actually changed this event (avoid re-triggering
    # on unrelated edits). On create, the assignment is intrinsic so we always fire.
    if payload.get("action") == "update":
        updated_from = payload.get("updatedFrom") or {}
        if "delegateId" not in updated_from and "assigneeId" not in updated_from:
            return False

    return True


def _create_task_for_issue(payload: dict[str, Any], integration: Integration) -> None:
    data = payload.get("data") or {}
    issue_id = data.get("id")
    if not issue_id:
        return
    issue_url = data.get("url") or ""

    team_id = integration.team_id

    # Logical dedup: at most one task per Linear issue per team.
    if tasks_facade.get_task_id_for_external_reference(
        team_id=team_id, kind=LINEAR_ISSUE_REFERENCE_KIND, external_id=str(issue_id)
    ):
        return

    # Tasks are attributed to the PostHog user who installed the integration (see spec §13b).
    user_id = integration.created_by_id
    if not user_id:
        logger.warning("linear_agent_webhook_missing_created_by", integration_id=integration.id)
        return

    identifier = data.get("identifier") or ""
    title = data.get("title") or "Untitled Linear issue"

    created = tasks_facade.create_and_run_task(
        team=integration.team,
        title=f"Linear {identifier}: {title}".strip(),
        description=_build_task_description(data, issue_url),
        origin_product=tasks_facade.TaskOriginProduct.LINEAR,
        user_id=user_id,
        repository=None,  # user selects a repo in the PostHog Code UI (spec option d)
        create_pr=True,
        mode="background",
    )

    tasks_facade.create_task_external_reference(
        team_id=team_id,
        task_id=created.task_id,
        kind=LINEAR_ISSUE_REFERENCE_KIND,
        external_id=str(issue_id),
        external_url=issue_url,
    )


def _build_task_description(data: dict[str, Any], issue_url: str) -> str:
    description = data.get("description") or ""
    if issue_url:
        suffix = f"\n\n---\nLinear issue: {issue_url}"
        return f"{description}{suffix}" if description else issue_url
    return description
