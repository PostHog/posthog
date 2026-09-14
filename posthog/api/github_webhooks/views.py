import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.api.github_webhooks.dispatch import dispatch_github_event
from posthog.api.github_webhooks.handlers import GITHUB_WEBHOOK_HANDLERS
from posthog.api.github_webhooks.signature import get_github_webhook_secret, verify_github_signature


@csrf_exempt
def github_webhook(request: HttpRequest) -> HttpResponse:
    """Unified GitHub App webhook dispatcher.

    Verifies the HMAC-SHA256 signature once, parses JSON once, then routes by
    ``X-GitHub-Event`` to every registered product handler. Each handler runs in
    isolation: one handler raising is logged and captured but never blocks another
    handler or the response sent back to GitHub.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    secret = get_github_webhook_secret()
    if not secret:
        return HttpResponse("Webhook not configured", status=500)

    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature(request.body, signature, secret):
        return HttpResponse("Invalid signature", status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    event_type = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    return dispatch_github_event(request, event_type, payload, delivery_id, GITHUB_WEBHOOK_HANDLERS.get(event_type, []))
