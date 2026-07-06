import gzip
import json
import logging
from typing import Any, Optional, cast

from django.db import close_old_connections

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.organization import Organization
from posthog.models.user import User

from products.customer_analytics.backend.facade.api import notify_managers_of_usage_spike

from ee.billing.billing_manager import BillingManager
from ee.sqs.SQSConsumer import SQSConsumer

logger = logging.getLogger(__name__)

# PostHog's own team on Cloud US — owns the Customer-analytics accounts that inbound billing
# usage-spike events resolve against. Billing emits these spike messages to the US queue.
POSTHOG_SELF_TEAM_ID = 2


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
            elif message_type == "billing_activity":
                self._process_billing_activity(body)
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

    def _process_billing_activity(self, body: dict[str, Any]) -> None:
        """
        Write a billing-originated change (spend limits, addons/products) to the
        organization's activity log.

        The actor is resolved from the distinct_id the billing service carries in
        the message; when it is absent (system-origin changes such as Stripe
        webhooks or dunning) the row is written as a system activity.
        """
        organization_id = body.get("organization_id")
        if not organization_id:
            logger.error("Billing activity is missing organization_id")
            capture_exception(Exception("Billing activity is missing organization_id"))
            return

        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            logger.exception(f"Organization {organization_id} does not exist")
            capture_exception(
                Exception("Organization being consumed does not exist"),
                {"organization_id": organization_id},
            )
            return

        distinct_id = body.get("distinct_id")
        user = User.objects.filter(distinct_id=distinct_id).first() if distinct_id else None
        if distinct_id and user is None:
            logger.warning(
                "billing_activity.distinct_id_not_found",
                extra={"distinct_id": distinct_id, "organization_id": organization_id},
            )

        detail_data = body.get("detail") or {}
        changes = [
            Change(
                type=change.get("type", "Billing"),
                action=change.get("action", "changed"),
                field=change.get("field"),
                before=change.get("before"),
                after=change.get("after"),
            )
            for change in (detail_data.get("changes") or [])
        ]

        log_activity(
            organization_id=organization.id,
            team_id=None,
            user=user,
            was_impersonated=False,
            item_id=body.get("item_id") or str(organization.id),
            scope="Billing",
            activity=body.get("activity") or "updated",
            detail=Detail(name=detail_data.get("name"), changes=changes),
        )
