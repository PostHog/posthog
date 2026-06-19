import gzip
import json
import logging
from typing import Any, Optional, cast

from django.db import close_old_connections

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization

from products.customer_analytics.backend.services.usage_spike_notifications import notify_managers_of_usage_spike

from ee.billing.billing_manager import BillingManager
from ee.sqs.SQSConsumer import SQSConsumer

logger = logging.getLogger(__name__)

# PostHog's own team on Cloud US — owns the Customer-analytics accounts that inbound billing
# usage-spike events resolve against. Billing emits these spike messages to the US queue.
POSTHOG_SELF_TEAM_ID = 2
BILLING_COLLECTIONS_ACCESS_BLOCK_REASON = "collections_failed_payment"
BILLING_COLLECTIONS_INACTIVE_REASON = "Billing collections: payment failed"


class BillingConsumer(SQSConsumer):
    """
    SQS Consumer for processing billing-related messages.
    """

    def process_message(self, message: dict[str, Any]) -> None:
        """
        Process a billing-related SQS message.

        Args:
            message: The SQS message to process
        """
        close_old_connections()

        try:
            raw_body = message.get("Body", "{}")
            message_attributes = message.get("MessageAttributes", {})

            body = self._decompress_and_parse_message(raw_body, message_attributes)
            message_id = message.get("MessageId", "unknown")

            # Extract message type to determine processing logic
            message_type = body.get("type")

            logger.info(f"Processing billing message of type {message_type} with ID {message_id}")

            # Process different message types
            if message_type == "billing_customer_update":
                self._process_billing_customer_update(body)
            elif message_type == "usage_spike_detected":
                self._process_usage_spike_detected(body)
            elif message_type == "billing_collections_access_state_changed":
                self._process_collections_access_state_changed(body)
            # Add more message types as needed
            # elif message_type == "invoice_created":
            #     self._process_invoice_created(body)
            else:
                logger.warning(f"Unknown message type: {message_type} for message {message_id}")
                capture_exception(
                    Exception("Unknown message type"), {"message_id": message_id, "message_type": message_type}
                )

            # Delete the message after successful processing
            if self.delete_message(message["ReceiptHandle"]):
                logger.info(f"Successfully processed and deleted message {message_id}")
            else:
                logger.error(f"Failed to delete message", {"message_id": message_id})

        except json.JSONDecodeError as e:
            logger.exception(f"Invalid JSON in message body: {message.get('Body', '')[:100]}... Error: {e}")
            capture_exception(
                e, {"message_id": message_id, "message_type": message_type, "body": message.get("Body", "")[:100]}
            )
        except Exception as e:
            logger.exception(f"Error processing billing message: {e}")
            capture_exception(e, {"message_id": message_id, "message_type": message_type})

    def _decompress_and_parse_message(
        self, raw_body: str | bytes, message_attributes: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """
        Decompress and parse message body based on content encoding.

        Args:
            raw_body: The raw message body string or bytes
            message_attributes: Dictionary of message attributes containing encoding information

        Returns:
            dict: The parsed JSON object
        """
        if not message_attributes:
            message_attributes = {}

        content_encoding = message_attributes.get("content_encoding", {}).get("StringValue")

        if content_encoding == "gzip":
            try:
                if isinstance(raw_body, str):
                    import base64

                    try:
                        raw_body_bytes = base64.b64decode(raw_body)
                    except Exception:
                        raw_body_bytes = raw_body.encode("utf-8")
                else:
                    raw_body_bytes = raw_body

                decompressed_data = gzip.decompress(raw_body_bytes)
                return cast(dict[str, Any], json.loads(decompressed_data.decode("utf-8")))
            except Exception as e:
                logger.exception(f"Failed to decompress gzipped message: {str(e)}")
                capture_exception(e)
                raise

        try:
            return cast(dict[str, Any], json.loads(raw_body))
        except json.JSONDecodeError:
            preview = (
                raw_body[:100].decode("utf-8", errors="replace") if isinstance(raw_body, bytes) else raw_body[:100]
            )
            logger.exception(f"Invalid JSON in message body: {preview}...")
            raise

    def _process_billing_customer_update(self, body: dict[str, Any]) -> None:
        """
        Process a billing customer update message.

        Args:
            body: The parsed message body containing billing customer update data
        """
        organization_id = body.get("organization_id")
        data = body.get("data", {})

        if not organization_id:
            logger.error("Billing customer update is missing organization_id")
            capture_exception(Exception("Billing customer update is missing organization_id"))
            return

        logger.info(f"Processing billing customer update for {organization_id}")

        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            logger.exception(f"Organization {organization_id} does not exist")
            capture_exception(
                Exception(f"Organization being consumed does not exist"),
                {"organization_id": organization_id},
            )
            return

        license = get_cached_instance_license()
        billing_manager = BillingManager(license)
        billing_manager.update_org_details(organization, data)

        logger.info(f"Successfully processed billing customer update for {organization_id}")

    def _process_usage_spike_detected(self, body: dict[str, Any]) -> None:
        """Route a billing-detected usage spike to the account's CSM and Account Executive."""
        data = body.get("data", {})
        spike_id = data.get("spike_id")

        if not spike_id:
            logger.error("Usage spike message is missing spike_id")
            capture_exception(Exception("Usage spike message is missing spike_id"))
            return

        notify_managers_of_usage_spike(
            team_id=POSTHOG_SELF_TEAM_ID,
            spike_id=str(spike_id),
            spikes=data.get("spikes", []),
            organization_id=data.get("organization_id"),
            billing_id=data.get("billing_id"),
            stripe_customer_id=data.get("stripe_customer_id"),
            detected_at=data.get("detected_at"),
        )

    def _process_collections_access_state_changed(self, body: dict[str, Any]) -> None:
        """Apply a Billing collections org access block/unblock command."""
        data = body.get("data", {})
        organization_id = body.get("organization_id") or data.get("organization_id")
        billing_customer_id = (
            body.get("billing_customer_id")
            or body.get("customer_id")
            or data.get("billing_customer_id")
            or data.get("customer_id")
        )
        stripe_customer_id = body.get("stripe_customer_id") or data.get("stripe_customer_id")
        desired_state = body.get("desired_state") or data.get("desired_state")
        reason = body.get("reason") or data.get("reason")

        if not all([organization_id, billing_customer_id, stripe_customer_id, desired_state, reason]):
            logger.error(
                "Billing collections access state message is missing required fields",
                extra={
                    "organization_id": organization_id,
                    "billing_customer_id": billing_customer_id,
                    "stripe_customer_id": stripe_customer_id,
                    "desired_state": desired_state,
                    "reason": reason,
                },
            )
            capture_exception(Exception("Billing collections access state message is missing required fields"))
            return

        if reason != BILLING_COLLECTIONS_ACCESS_BLOCK_REASON:
            logger.error("Unsupported Billing collections access block reason", extra={"reason": reason})
            capture_exception(Exception("Unsupported Billing collections access block reason"), {"reason": reason})
            return

        if desired_state not in {"blocked", "unblocked"}:
            logger.error(
                "Unsupported Billing collections access desired state",
                extra={"desired_state": desired_state},
            )
            capture_exception(
                Exception("Unsupported Billing collections access desired state"),
                {"desired_state": desired_state},
            )
            return

        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            logger.exception(f"Organization {organization_id} does not exist")
            capture_exception(
                Exception("Organization for Billing collections access state does not exist"),
                {"organization_id": organization_id},
            )
            return

        if organization.customer_id != str(billing_customer_id):
            logger.error(
                "Billing collections access state customer mismatch",
                extra={
                    "organization_id": organization_id,
                    "organization_customer_id": organization.customer_id,
                    "billing_customer_id": billing_customer_id,
                    "stripe_customer_id": stripe_customer_id,
                },
            )
            capture_exception(
                Exception("Billing collections access state customer mismatch"),
                {
                    "organization_id": organization_id,
                    "organization_customer_id": organization.customer_id,
                    "billing_customer_id": billing_customer_id,
                    "stripe_customer_id": stripe_customer_id,
                },
            )
            return

        if desired_state == "blocked":
            if (
                organization.is_active is False
                and organization.is_not_active_reason != BILLING_COLLECTIONS_INACTIVE_REASON
            ):
                logger.info(
                    "Skipping Billing collections block because organization is already inactive for another reason",
                    extra={
                        "organization_id": organization_id,
                        "organization_customer_id": organization.customer_id,
                        "billing_customer_id": billing_customer_id,
                        "stripe_customer_id": stripe_customer_id,
                        "is_not_active_reason": organization.is_not_active_reason,
                    },
                )
                return

            organization.is_active = False
            organization.is_not_active_reason = BILLING_COLLECTIONS_INACTIVE_REASON
            organization.save(update_fields=["is_active", "is_not_active_reason", "updated_at"])
        else:
            if (
                organization.is_active is False
                and organization.is_not_active_reason == BILLING_COLLECTIONS_INACTIVE_REASON
            ):
                organization.is_active = True
                organization.is_not_active_reason = None
                organization.save(update_fields=["is_active", "is_not_active_reason", "updated_at"])
