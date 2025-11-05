import hmac
import json
import hashlib
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.helpers.email_utils import EmailLookupHandler
from posthog.models.user import User

logger = structlog.get_logger(__name__)


def verify_customerio_signature(body: bytes, signature: str, signing_key: str) -> bool:
    """
    Verify Customer.io webhook signature using HMAC-SHA256.
    Customer.io computes: HMAC-SHA256(signing_key, body)
    """
    expected_signature = hmac.new(signing_key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


@method_decorator(csrf_exempt, name="dispatch")
class CustomerIoWebhookView(View):
    """
    Webhook endpoint for Customer.io reporting events.
    Handles email delivery events and tracks delivery time for verification/MFA emails.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            signing_key = getattr(settings, "CUSTOMER_IO_WEBHOOK_SIGNING_KEY", None)
            if not signing_key:
                logger.warning("Customer.io webhook signing key not configured")
                return JsonResponse({"error": "Webhook not configured"}, status=503)

            # Get signature from headers
            signature = request.headers.get("x-cio-signature", "")
            timestamp = request.headers.get("x-cio-timestamp", "")

            if not signature or not timestamp:
                logger.warning("Missing Customer.io webhook signature or timestamp")
                return JsonResponse({"error": "Missing signature or timestamp"}, status=400)

            # Verify signature
            body = request.body
            if not verify_customerio_signature(body, signature, signing_key):
                logger.warning("Invalid Customer.io webhook signature")
                return JsonResponse({"error": "Invalid signature"}, status=403)

            # Parse webhook payload
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON in Customer.io webhook", error=str(e))
                return JsonResponse({"error": "Invalid JSON"}, status=400)

            # Process webhook event
            self._process_event(payload)

            return JsonResponse({"status": "ok"})

        except Exception as e:
            logger.exception("Error processing Customer.io webhook", error=str(e))
            capture_exception(e)
            return JsonResponse({"error": "Internal server error"}, status=500)

    def _process_event(self, payload: dict[str, Any]) -> None:
        """
        Process a Customer.io webhook event.
        We're interested in:
        - email.sent: Track when email was sent to Customer.io
        - email.delivered: Track when email was delivered, calculate delivery time
        """
        object_type = payload.get("object_type")
        metric = payload.get("metric")
        data = payload.get("data", {})
        # Only process email events
        if object_type != "email":
            return

        # Get email address from payload
        recipient = data.get("recipient") or data.get("identifiers", {}).get("email")
        if not recipient:
            logger.warning("No recipient email in Customer.io webhook payload", payload=payload)
            return

        # Get user by email to get distinct_id
        user = EmailLookupHandler.get_user_by_email(recipient)
        if not user:
            logger.debug("No user found for email in Customer.io webhook", email=recipient)
            return

        if not user.distinct_id:
            logger.warning("User has no distinct_id", user_id=user.id, email=recipient)
            return

        # Process based on metric type
        if metric == "sent":
            self._handle_email_sent(user, payload, data)
        elif metric == "delivered":
            self._handle_email_delivered(user, payload, data)
        elif metric == "bounced":
            self._handle_email_bounced(user, payload, data)

    def _handle_email_sent(self, user: User, payload: dict[str, Any], data: dict[str, Any]) -> None:
        """
        Store sent timestamp for delivery time calculation.
        Uses delivery_id as the cache key to correlate sent and delivered events.
        """
        sent_timestamp = payload.get("timestamp")
        delivery_id = data.get("delivery_id")
        if not sent_timestamp or not delivery_id:
            logger.debug("Missing timestamp or delivery_id in sent event", payload=payload)
            return

        # Store sent timestamp keyed by delivery_id
        # TTL of 24 hours - delivery should happen within this window
        cache_key = f"customerio_email_sent:{delivery_id}"
        cache.set(cache_key, sent_timestamp, timeout=86400)  # 24 hours

        logger.debug(
            "Stored email sent timestamp",
            user_id=user.id,
            delivery_id=delivery_id,
            sent_timestamp=sent_timestamp,
        )

    def _handle_email_delivered(self, user: User, payload: dict[str, Any], data: dict[str, Any]) -> None:
        """
        Track email delivery and calculate delivery time.
        We need to:
        1. Identify which email type this is (verification vs MFA)
        2. Find the corresponding "sent" event timestamp
        3. Calculate delivery_time = delivered_timestamp - sent_timestamp
        4. Emit PostHog event with delivery_time_seconds
        """
        delivered_timestamp = payload.get("timestamp")
        if not delivered_timestamp:
            logger.warning("No timestamp in delivered event", payload=payload)
            return
        # Try to identify email type from subject or other data
        # For now, we'll check if it matches our email patterns
        subject = data.get("subject", "")
        email_type = None
        event_name = None

        if "verify your email" in subject.lower() or "email verification" in subject.lower():
            email_type = "verification"
            event_name = "verification email delivered"
        elif "verify your posthog login" in subject.lower() or "mfa" in subject.lower():
            email_type = "mfa"
            event_name = "email mfa link delivered"

        if not email_type:
            logger.debug("Unknown email type in Customer.io webhook", subject=subject)
            return

        # Retrieve sent timestamp using delivery_id
        delivery_id = data.get("delivery_id")
        sent_timestamp = None

        if delivery_id:
            cache_key = f"customerio_email_sent:{delivery_id}"
            sent_timestamp = cache.get(cache_key)

        properties: dict[str, Any] = {
            "email_type": email_type,
        }

        # Calculate delivery time if we have sent timestamp
        if sent_timestamp:
            delivery_time = delivered_timestamp - sent_timestamp
            properties["delivery_time_seconds"] = delivery_time
            logger.debug(
                "Calculated delivery time",
                user_id=user.id,
                email_type=email_type,
                delivery_time_seconds=delivery_time,
            )
        else:
            logger.debug(
                "Could not find sent timestamp for delivery event",
                user_id=user.id,
                delivery_id=delivery_id,
            )

        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event=event_name,
            properties=properties,
            groups={"organization": str(user.current_organization.id)} if user.current_organization else None,
        )

        logger.info(
            "Email delivered event tracked",
            user_id=user.id,
            email_type=email_type,
            event_name=event_name,
        )

    def _handle_email_bounced(self, user: User, payload: dict[str, Any], data: dict[str, Any]) -> None:
        """Track email bounce events"""
        failure_message = data.get("failure_message", "")

        subject = data.get("subject", "")
        email_type = None
        event_name = None

        if "verify your email" in subject.lower():
            email_type = "verification"
            event_name = "verification email bounced"
        elif "verify your posthog login" in subject.lower() or "mfa" in subject.lower():
            email_type = "mfa"
            event_name = "email mfa link bounced"

        if email_type:
            posthoganalytics.capture(
                distinct_id=str(user.distinct_id),
                event=event_name,
                properties={
                    "email_type": email_type,
                    "failure_message": failure_message,
                },
                groups={"organization": str(user.current_organization.id)} if user.current_organization else None,
            )
