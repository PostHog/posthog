import datetime
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from smart_open import smart_open

from posthog.api.capture import log_event
from posthog.celery import app as celery_app
from posthog.utils import is_clickhouse_enabled


class Command(BaseCommand):
    help = "Consume from a Kafka topic into S3"

    def add_arguments(self, parser):
        parser.add_argument("--bucket-path", default=None)

    def handle(self, *args, **options):
        if not options["bucket-path"]:
            print("The argument --bucket-path is required")
            exit(1)

        bucket_path = options["bucket-path"]

        files_to_read = os.environ.get("S3_IMPORT_FILES").split(",")

        ordered_files = []

        # read one line from each bucket and sort by timestamp
        for file_name in files_to_read:
            line_index = 0
            for line in smart_open(f"s3://{bucket_path}{file_name}", "rb"):
                if line_index == 1:
                    timestamp = datetime.datetime.fromisoformat(line.split(",")[5])
                    ordered_files.append((timestamp, file_name))
                    break
                line_index += 1

        ordered_files.sort()

        # read all files and capture events
        for _, file_name in ordered_files:
            is_first_line = True
            for line in smart_open(f"s3://{bucket_path}{file_name}", "rb"):
                if is_first_line:
                    is_first_line = False
                    continue
                [
                    distinct_id,
                    ip,
                    site_url,
                    data,
                    team_id,
                    now,
                    sent_at,
                    event_uuid,
                ] = line.split(",")

            if is_clickhouse_enabled():
                log_event(
                    distinct_id=distinct_id,
                    ip=ip,
                    site_url=site_url,
                    data=json.loads(data),
                    team_id=team_id,
                    now=now,
                    sent_at=sent_at,
                    event_uuid=event_uuid,
                )
            else:
                task_name = "posthog.tasks.process_event.process_event_with_plugins"
                celery_queue = settings.PLUGINS_CELERY_QUEUE
                celery_app.send_task(
                    name=task_name,
                    queue=celery_queue,
                    args=[
                        distinct_id,
                        ip,
                        site_url,
                        json.loads(data),
                        team_id,
                        now.isoformat(),
                        sent_at,
                    ],
                )
