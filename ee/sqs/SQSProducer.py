import json
import uuid
import logging

from django.conf import settings

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def get_sqs_producer(queue_name):
    """
    Get an SQS producer instance for a named queue from Django settings.

    Args:
        queue_name (str): The name of the queue as defined in settings.SQS_QUEUES

    Returns:
        SQSProducer: An initialized SQS producer, or None if queue not found
    """
    queues = getattr(settings, "SQS_QUEUES", {})
    queue_settings = queues.get(queue_name)

    if not queue_settings:
        logger.error(f"Queue '{queue_name}' not found in settings")
        return None

    return SQSProducer(
        queue_url=queue_settings.get("url") if queue_settings and "url" in queue_settings else None,
        region_name=queue_settings.get("region", "us-east-1"),
    )


class SQSProducer:
    """
    A class for sending messages to an AWS SQS queue.
    """

    def __init__(self, queue_url, region_name="us-east-1"):
        """
        Initialize the SQS producer.

        Args:
            queue_url (str): The URL of the SQS queue
            region_name (str): AWS region name
        """
        self.queue_url = queue_url

        self.sqs = boto3.client(
            "sqs",
            region_name=region_name,
        )

    def send_message(
        self, message_body, message_attributes=None, delay_seconds=0, group_id=None, deduplication_id=None
    ):
        """
        Send a message to the SQS queue.

        Args:
            message_body (dict): The message body to send
            message_attributes (dict, optional): Message attributes
            delay_seconds (int, optional): Delay delivery of the message in seconds (0-900)
            group_id (str, optional): Message group ID for FIFO queues
            deduplication_id (str, optional): Message deduplication ID for FIFO queues

        Returns:
            dict: Response from SQS containing MessageId if successful, None if failed
        """
        if isinstance(message_body, dict):
            message_body = json.dumps(message_body)

        params = {"QueueUrl": self.queue_url, "MessageBody": message_body, "DelaySeconds": delay_seconds}

        if message_attributes:
            formatted_attributes = self._format_message_attributes(message_attributes)
            if formatted_attributes:
                params["MessageAttributes"] = formatted_attributes

        # For FIFO queues, add required parameters
        if group_id:
            params["MessageGroupId"] = group_id

            if not deduplication_id:
                deduplication_id = str(uuid.uuid4())

            params["MessageDeduplicationId"] = deduplication_id

        try:
            response = self.sqs.send_message(**params)
            message_id = response.get("MessageId")
            logger.info(f"Message sent successfully with ID: {message_id}")
            return response

        except ClientError as e:
            logger.exception(f"Error sending message: {e}")
            return None

    def _format_message_attributes(self, attributes):
        """
        Format message attributes for the SQS API.

        Args:
            attributes (dict): Message attributes

        Returns:
            dict: Formatted message attributes
        """
        formatted_attributes = {}

        for key, value in attributes.items():
            attribute_type = "String"

            if isinstance(value, int):
                attribute_type = "Number"
                value = str(value)
            elif isinstance(value, bytes):
                attribute_type = "Binary"
            elif isinstance(value, list | dict):
                attribute_type = "String"
                value = json.dumps(value)
            elif not isinstance(value, str):
                value = str(value)

            formatted_attributes[key] = {
                "DataType": attribute_type,
                "StringValue": value if attribute_type != "Binary" else None,
                "BinaryValue": value if attribute_type == "Binary" else None,
            }

            formatted_attributes[key] = {k: v for k, v in formatted_attributes[key].items() if v is not None}

        return formatted_attributes
