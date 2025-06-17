import logging
from typing import Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ee.billing.queue.BillingConsumer import BillingConsumer
from ee.sqs.SQSConsumer import SQSConsumer

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs a consumer for SQS queues"

    def add_arguments(self, parser):
        parser.add_argument("--queue", type=str, required=True, help="Queue name to consume from (defined in settings)")
        parser.add_argument(
            "--continuous", action="store_true", default=False, help="Run continuously (default: False)"
        )
        parser.add_argument(
            "--max-messages", type=int, default=10, help="Maximum number of messages to process in one batch"
        )

    def handle(self, *args, **options):
        queue_name = options.get("queue")
        continuous = options.get("continuous", False)
        max_messages = options.get("max_messages", 10)

        if not queue_name:
            raise CommandError("Please specify a queue name")

        # Get queue settings from Django settings
        queues = getattr(settings, "SQS_QUEUES", {})
        queue_settings = queues.get(queue_name)

        if not queue_settings:
            raise CommandError(f'Queue "{queue_name}" not found in settings')

        # Get the queue URL and region
        queue_url = queue_settings.get("url")
        region_name = queue_settings.get("region", "us-east-1")

        if not queue_url:
            raise CommandError(f'Queue URL not defined for queue "{queue_name}"')

        # Get the queue type to determine which consumer to use
        queue_type = queue_settings.get("type", "default")
        consumer = self._get_consumer(queue_type, queue_url, region_name)

        if not consumer:
            raise CommandError(f"Unknown queue type: {queue_type}")

        self.stdout.write(f'Starting consumer for queue "{queue_name}" ({queue_type})')
        consumer.run(max_messages=max_messages, continuous=continuous)

    def _get_consumer(self, queue_type: str, queue_url: str, region_name: str) -> Optional[SQSConsumer]:
        """
        Factory method to get the appropriate consumer based on queue type.

        Args:
            queue_type: The type of queue to consume from
            queue_url: The URL of the SQS queue
            region_name: AWS region name

        Returns:
            An initialized SQS consumer instance
        """
        if queue_type == "billing":
            return BillingConsumer(queue_url=queue_url, region_name=region_name)
        # Add more consumer types as needed
        # elif queue_type == "another_type":
        #     return AnotherTypeConsumer(queue_url=queue_url, region_name=region_name)

        # Unknown queue type
        logger.error(f"Unknown queue type: {queue_type}")
        return None
