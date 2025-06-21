import gzip
import json
import logging
from typing import Any, Optional

from ee.billing.billing_manager import BillingManager
from posthog.models.organization import Organization
from posthog.cloud_utils import get_cached_instance_license

from ee.sqs.SQSConsumer import SQSConsumer

logger = logging.getLogger(__name__)


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
            # Add more message types as needed
            # elif message_type == "invoice_created":
            #     self._process_invoice_created(body)
            else:
                logger.warning(f"Unknown message type: {message_type} for message {message_id}")

            # Delete the message after successful processing
            if self.delete_message(message["ReceiptHandle"]):
                logger.info(f"Successfully processed and deleted message {message_id}")
            else:
                logger.error(f"Failed to delete message {message_id}")

        except json.JSONDecodeError as e:
            logger.exception(f"Invalid JSON in message body: {message.get('Body', '')[:100]}... Error: {e}")
        except Exception as e:
            logger.exception(f"Error processing billing message: {e}")

    def _decompress_and_parse_message(self, raw_body: str, message_attributes: Optional[dict] = None) -> dict:
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
                        raw_body = base64.b64decode(raw_body)
                    except Exception:
                        raw_body = raw_body.encode("utf-8")

                decompressed_data = gzip.decompress(raw_body)
                return json.loads(decompressed_data.decode("utf-8"))
            except Exception as e:
                logger.exception(f"Failed to decompress gzipped message: {str(e)}")
                raise

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError:
            logger.exception(f"Invalid JSON in message body: {raw_body[:100]}...")
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
            return

        logger.info(f"Processing billing customer update for {organization_id}")

        organization = Organization.objects.get(id=organization_id)
        license = get_cached_instance_license()
        billing_manager = BillingManager(license)
        billing_manager.update_org_details(organization, data)

        logger.info(f"Successfully processed billing customer update for {organization_id}")
