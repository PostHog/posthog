import csv
import datetime
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from smart_open import smart_open

from posthog.celery import app as celery_app
from posthog.utils import is_clickhouse_enabled
import re

def match_snapshot(haystack):
    needle = "event.*:.*\$snapshot."
    return bool(re.search(needle, haystack))

class Command(BaseCommand):
    help = "Consume from a Kafka topic into S3"

    def add_arguments(self, parser):
        parser.add_argument("--bucketpath", default=None)
        parser.add_argument("--teamids", default=None)
        parser.add_argument("--teamidsignore", default=None)

    def handle(self, *args, **options):
        if not options["bucketpath"]:
            print("The argument --bucket-path is required")
            exit(1)

        bucket_path = options["bucketpath"]


        files_to_read = os.environ.get("S3_IMPORT_FILES").split(",")

        ordered_files = []

        print(files_to_read)

        csv.field_size_limit(9999999999999)

        # read one line from each file and sort by timestamp to process events in order
        for file_name in files_to_read:
            line_index = 0
            for line in smart_open(f"s3://{bucket_path}{file_name}", "rb"):
                decoded_line = line.decode("utf-8")
                if match_snapshot(decoded_line):
                    # print('skipping $snapshot event')
                    continue
                if line_index == 1:
                    for row in csv.reader([line.decode("utf-8")]):
                        timestamp = datetime.datetime.fromisoformat(row[5])
                        ordered_files.append((timestamp, file_name))
                        break
                    break
                line_index += 1

        ordered_files.sort()

        print(ordered_files)

        total_events_processed = 0

        # read all files and capture events
        for _, file_name in ordered_files:
            is_first_line = True
            for line in smart_open(f"s3://{bucket_path}{file_name}", "rb"):
                if is_first_line:
                    is_first_line = False
                    continue

                total_events_processed += 1
                print('total events processed:', total_events_processed)

                decoded_line = line.decode('utf-8')
                if match_snapshot(decoded_line):
                    # print('skipping $snapshot event')
                    continue

                team_ids = options["teamids"].split(',') if options["teamids"] else []
                team_ids_ignore = options["teamidsignore"].split(',') if options["teamidsignore"] else []
                for row in csv.reader([decoded_line]):
                    if (len(team_ids) and row[4] not in team_ids) or row[4] in team_ids_ignore:
                        # print(f"skipping event not from target team")
                        continue

                    # print(
                    #     {
                    #         "distinct_id": row[0],
                    #         "site_url": row[1],
                    #         "ip": row[2],
                    #         "data": json.loads(row[3]),
                    #         "team_id": int(row[4]),
                    #         "now": row[5],
                    #         "sent_at": row[6],
                    #         "event_uuid": row[7],
                    #     }
                    # )

                    print(row[5])

                    if is_clickhouse_enabled():
                        from posthog.api.capture import log_event
                        log_event(
                            distinct_id=row[0],
                            site_url=row[1],
                            ip=row[2],
                            data=json.loads(row[3]),
                            team_id=int(row[4]),
                            now=datetime.datetime.fromisoformat(row[5]),
                            sent_at=row[6],
                            event_uuid=row[7],
                        )
                    else:
                        task_name = "posthog.tasks.process_event.process_event_with_plugins"
                        celery_queue = settings.PLUGINS_CELERY_QUEUE
                        celery_app.send_task(
                            name=task_name,
                            queue=celery_queue,
                            args=[
                                row[0],
                                row[2],
                                row[1],
                                json.loads(row[3]),
                                int(row[4]),
                                row[5],
                                row[6],
                            ],
                        )
