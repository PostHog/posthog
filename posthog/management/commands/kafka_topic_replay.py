import datetime
import json
from zipfile import ZipFile

import boto3
from django.core.management.base import BaseCommand

from ee.kafka_client.helper import get_kafka_consumer

ONE_MB = 1000000


class Command(BaseCommand):
    help = "Consume from a Kafka topic into S3"

    def add_arguments(self, parser):
        parser.add_argument("--topic", default=None)

    def handle(self, *args, **options):
        if not options["topic"]:
            print("The argument --topic is required")
            exit(1)

        s3 = boto3.resource("s3")

        consumer = get_kafka_consumer(options["topic"])

        current_size = 0

        json_data = "["

        for message in consumer:
            event = message.value
            current_size += message.serialized_value_size

            is_last_message_in_batch = current_size > 500 * ONE_MB
            # if it fails to compare, just get the message
            try:
                if datetime.datetime.fromisoformat(event["now"]) < datetime.datetime.fromisoformat(
                    "2021-09-22T00:00:00.000+00:00"
                ):
                    continue
            except:
                pass

            json_data += event

            if not is_last_message_in_batch:
                json_data += ","
            else:
                json_data += "]"

            if is_last_message_in_batch:
                last_timestamp = json.loads(event)["now"]
                zipped_file = ZipFile(f"{last_timestamp}.zip", "w")
                zipped_file.writestr(f"{last_timestamp}.json", json_data)
                zipped_file.close()
                s3.meta.client.upload_file(f"{last_timestamp}.zip", "kafka-recovery-230921", f"{last_timestamp}.zip")
                json_data = "["
