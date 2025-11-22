import gzip
import json
import base64
import logging
from typing import Any

from django.db import close_old_connections

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization

from ee.billing.billing_manager import BillingManager
from ee.billing.marketplace.submitter import MarketplaceSubmitter
from ee.sqs.SQSConsumer import SQSConsumer

logger = logging.getLogger(__name__)


class BillingConsumer(SQSConsumer):
    """SQS Consumer for processing billing-related messages."""

    def process_message(self, message: dict[str, Any]) -> None:
        close_old_connections()

        message_id = message.get("MessageId", "unknown")
        message_type = None

        try:
            body = self._parse_message(message)
            message_type = body.get("type")

            logger.info(f"Processing billing message of type {message_type} with ID {message_id}")

            self._dispatch(message_type, body, message_id)
            self._acknowledge(message, message_id)

        except json.JSONDecodeError as e:
            logger.exception(f"Invalid JSON in message body: {message.get('Body', '')[:100]}...")
            capture_exception(e, {"message_id": message_id, "body": message.get("Body", "")[:100]})
        except Exception as e:
            logger.exception(f"Error processing billing message: {e}")
            capture_exception(e, {"message_id": message_id, "message_type": message_type})

    def _parse_message(self, message: dict[str, Any]) -> dict:
        raw_body = message.get("Body", "{}")
        message_attributes = message.get("MessageAttributes", {})
        return self._decompress_and_parse(raw_body, message_attributes)

    def _dispatch(self, message_type: str | None, body: dict[str, Any], message_id: str) -> None:
        handlers = {
            "billing_customer_update": self._handle_billing_customer_update,
            "invoice_finalized": self._handle_invoice_submission,
            "marketplace.invoice.submit": self._handle_invoice_submission,
            "marketplace.usage.submit": self._handle_usage_submission,
        }

        handler = handlers.get(message_type)
        if handler:
            handler(body)
        else:
            logger.warning(f"Unknown message type: {message_type} for message {message_id}")
            capture_exception(
                Exception("Unknown message type"),
                {"message_id": message_id, "message_type": message_type},
            )

    def _acknowledge(self, message: dict[str, Any], message_id: str) -> None:
        if self.delete_message(message["ReceiptHandle"]):
            logger.info(f"Successfully processed and deleted message {message_id}")
        else:
            logger.error(f"Failed to delete message {message_id}")

    def _decompress_and_parse(self, raw_body: str, message_attributes: dict | None = None) -> dict:
        content_encoding = (message_attributes or {}).get("content_encoding", {}).get("StringValue")

        if content_encoding == "gzip":
            return self._decompress_gzip(raw_body)

        return json.loads(raw_body)

    def _decompress_gzip(self, raw_body: str | bytes) -> dict:
        try:
            if isinstance(raw_body, str):
                try:
                    raw_body = base64.b64decode(raw_body)
                except Exception:
                    raw_body = raw_body.encode("utf-8")

            decompressed = gzip.decompress(raw_body)
            return json.loads(decompressed.decode("utf-8"))
        except Exception as e:
            logger.exception(f"Failed to decompress gzipped message: {e}")
            capture_exception(e)
            raise

    def _handle_billing_customer_update(self, body: dict[str, Any]) -> None:
        organization_id = body.get("organization_id")
        data = body.get("data", {})

        if not organization_id:
            self._log_missing_field("billing_customer_update", "organization_id")
            return

        logger.info(f"Processing billing customer update for {organization_id}")

        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            logger.warning(f"Organization {organization_id} does not exist")
            capture_exception(
                Exception("Organization being consumed does not exist"),
                {"organization_id": organization_id},
            )
            return

        license = get_cached_instance_license()
        billing_manager = BillingManager(license)
        billing_manager.update_org_details(organization, data)

        logger.info(f"Successfully processed billing customer update for {organization_id}")

    def _handle_invoice_submission(self, body: dict[str, Any]) -> None:
        organization_id = body.get("organization_id")
        invoice_id = body.get("invoice_id")

        if not organization_id or not invoice_id:
            self._log_missing_field("invoice_submission", "organization_id or invoice_id")
            return

        MarketplaceSubmitter(organization_id).submit_invoice(invoice_id)

    def _handle_usage_submission(self, body: dict[str, Any]) -> None:
        organization_id = body.get("organization_id")

        if not organization_id:
            self._log_missing_field("usage_submission", "organization_id")
            return

        MarketplaceSubmitter(organization_id).submit_usage()

    def _log_missing_field(self, handler_name: str, field_name: str) -> None:
        logger.error(f"{handler_name} missing required field: {field_name}")
        capture_exception(Exception(f"{handler_name} missing required field: {field_name}"))
