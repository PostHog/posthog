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

        # Initialize SQS client
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
        # Convert dict to JSON string
        if isinstance(message_body, dict):
            message_body = json.dumps(message_body)

        # Prepare the send message parameters
        params = {"QueueUrl": self.queue_url, "MessageBody": message_body, "DelaySeconds": delay_seconds}

        # Add message attributes if provided
        if message_attributes:
            formatted_attributes = self._format_message_attributes(message_attributes)
            if formatted_attributes:
                params["MessageAttributes"] = formatted_attributes

        # For FIFO queues, add required parameters
        if group_id:
            params["MessageGroupId"] = group_id

            # Generate a deduplication ID if not provided
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

    # def send_message_batch(self, messages, delay_seconds=0):
    #     """
    #     Send multiple messages to the SQS queue in a single batch.

    #     Args:
    #         messages (list): List of message dicts to send
    #         delay_seconds (int, optional): Default delay for messages (0-900)

    #     Returns:
    #         dict: Response from SQS containing successful and failed messages
    #     """
    #     # Check if we have messages to send
    #     if not messages:
    #         logger.warning("No messages to send in batch")
    #         return None

    #     # Prepare batch entries (maximum 10 per API call)
    #     entries = []
    #     for i, msg in enumerate(messages[:10]):
    #         # Generate an ID for this message in the batch
    #         entry_id = f"msg-{i}-{uuid.uuid4()}"

    #         # Get message body
    #         body = msg.get("body", {})
    #         if isinstance(body, dict):
    #             body = json.dumps(body)

    #         # Create entry for this message
    #         entry = {"Id": entry_id, "MessageBody": body, "DelaySeconds": msg.get("delay_seconds", delay_seconds)}

    #         # Add message attributes if provided
    #         attributes = msg.get("attributes")
    #         if attributes:
    #             formatted_attributes = self._format_message_attributes(attributes)
    #             if formatted_attributes:
    #                 entry["MessageAttributes"] = formatted_attributes

    #         # For FIFO queues, add required parameters
    #         group_id = msg.get("group_id")
    #         if group_id:
    #             entry["MessageGroupId"] = group_id

    #             # Get or generate deduplication ID
    #             dedup_id = msg.get("deduplication_id")
    #             if not dedup_id:
    #                 dedup_id = str(uuid.uuid4())

    #             entry["MessageDeduplicationId"] = dedup_id

    #         entries.append(entry)

    #     try:
    #         response = self.sqs.send_message_batch(QueueUrl=self.queue_url, Entries=entries)

    #         # Log successful and failed messages
    #         successful = response.get("Successful", [])
    #         failed = response.get("Failed", [])

    #         if successful:
    #             logger.info(f"Successfully sent {len(successful)} messages in batch")

    #         if failed:
    #             logger.error(f"Failed to send {len(failed)} messages in batch: {failed}")

    #         return response

    #     except ClientError as e:
    #         logger.exception(f"Error sending message batch: {e}")
    #         return None

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
            attribute_type = "String"  # Default type

            # Determine the data type
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

            # Remove None values
            formatted_attributes[key] = {k: v for k, v in formatted_attributes[key].items() if v is not None}

        return formatted_attributes
