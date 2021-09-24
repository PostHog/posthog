import json
import os

import boto3
from django.core.management.base import BaseCommand
from django.db import connection
from smart_open import smart_open

from ee.kafka_client.helper import get_kafka_consumer


class Command(BaseCommand):
    help = "Consume from a Kafka topic into S3"

    def add_arguments(self, parser):
        parser.add_argument("--bucket", default=None)

    def handle(self, *args, **options):
        if not options["bucket"]:
            print("The argument --bucket is required")
            exit(1)

        i = 0
        # stream lines from an S3 object
        for line in smart_open(
            "s3://yakko-athena-test/results/Unsaved/2021/09/24/f3bc23f5-de44-492c-83fb-981af768e9ad.csv", "rb"
        ):
            if i == 1:
                print(
                    json.loads(
                        line.decode("utf8")
                        .replace('"""', '"')
                        .replace('""', '"')
                        .replace("\\", "")
                        .replace('"{', "{")
                        .replace('}"', "}")
                    )
                )
            i += 1
            if i == 2:
                break

        # objects_to_read = set(os.getenv('S3_FILES', ',').split(','))
        # s3 = boto3.resource("s3")

        # bucket = s3.Bucket(options["bucket"])
        # for obj in bucket.objects.all():
        #     key = obj.key
        #     print(key)
        #     if key in objects_to_read:
        #         print('woop')
        # body = obj.get()['Body'].read()
