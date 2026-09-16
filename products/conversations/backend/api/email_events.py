"""Email webhook endpoints for Mailgun routes.

Three routes on one Mailgun account: the inbox address a customer writes to, the address a
customer's own agent blind-copies, and the catch-all that serves both. Each is an ingress app,
so verification, the receipt and the forward to the owning region all happen there, and the work
runs in `products/conversations/backend/services/mailgun_events.py`.
"""

from posthog.ingress.mailgun.provider import build_mailgun_provider
from posthog.ingress.views import build_webhook_view

from products.conversations.backend.mailgun import get_email_webhook_signing_key

email_inbound_handler = build_webhook_view(
    build_mailgun_provider("inbound", signing_key_getter=get_email_webhook_signing_key)
)
email_outbound_handler = build_webhook_view(
    build_mailgun_provider("outbound", signing_key_getter=get_email_webhook_signing_key)
)
email_capture_handler = build_webhook_view(
    build_mailgun_provider("capture", signing_key_getter=get_email_webhook_signing_key)
)
