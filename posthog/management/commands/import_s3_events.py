import csv
import json
import os
import re
import threading
from multiprocessing import Queue

from dateutil import parser
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from smart_open import smart_open

from posthog.celery import app as celery_app
from posthog.utils import is_clickhouse_enabled

TARGET_QUEUES = 20


def produce_event(q, i):
    while True:
        payload = q.get()
        if payload == "done":
            print(f"Queue {i} done.", i)
            q.close()
            return

        row = payload
        # print(f'Queue {i} processing ', row[7])

        if is_clickhouse_enabled():
            from posthog.api.capture import log_event

            log_event(
                distinct_id=row[0],
                site_url=row[1],
                ip=row[2],
                data=json.loads(row[3]),
                team_id=int(row[4]),
                now=parser.parse(row[5]),
                sent_at=parser.parse(row[6]) if row[6] else None,
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


def match_snapshot(haystack):
    needle = r"event.*:.*\$snapshot."
    return bool(re.search(needle, haystack))


class Command(BaseCommand):
    help = "Consume from a Kafka topic into S3"

    def add_arguments(self, parser):
        parser.add_argument("--bucketpath", default=None)
        parser.add_argument("--teamids", default=None)
        parser.add_argument("--teamidsignore", default=None)
        parser.add_argument("--startindex", default=None)

    def handle(self, *args, **options):
        if not options["bucketpath"]:
            print("The argument --bucket-path is required")
            exit(1)

        queues = []
        threads = []
        for i in range(TARGET_QUEUES):
            q = Queue()
            thread = threading.Thread(
                target=produce_event,
                args=(
                    q,
                    i,
                ),
            )
            thread.start()
            threads.append(thread)
            queues.append(q)

        bucket_path = options["bucketpath"]

        files_to_read = os.environ.get("S3_IMPORT_FILES").split(",")

        ordered_files = []

        print(files_to_read)

        csv.field_size_limit(99999999999)

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
                        timestamp = parser.parse(row[5])
                        ordered_files.append((timestamp, file_name))
                        break
                    break
                line_index += 1

        ordered_files.sort()

        print(ordered_files)

        total_events_processed = 0
        snapshot_events = 0
        failed_events = 0

        team_ids = options["teamids"].split(",") if options["teamids"] else []
        team_ids_ignore = options["teamidsignore"].split(",") if options["teamidsignore"] else []
        start_index = int(options["startindex"]) + 1 if options["startindex"] else 1

        # read all files and capture events
        for _, file_name in ordered_files:
            is_first_line = True
            for line in smart_open(f"s3://{bucket_path}{file_name}", "rb"):
                if is_first_line:
                    is_first_line = False
                    continue

                total_events_processed += 1
                print("total events processed:", total_events_processed)

                if total_events_processed < start_index:
                    continue

                decoded_line = line.decode("utf-8")
                if match_snapshot(decoded_line):
                    snapshot_events += 1
                    print("skipping $snapshot event number", snapshot_events)
                    continue

                for row in csv.reader([decoded_line]):

                    try:
                        if (len(team_ids) and row[4] not in team_ids) or row[4] in team_ids_ignore:
                            continue
                        print(row[5])
                        part_key = int(row[0].encode("utf-8").hex(), 16) % TARGET_QUEUES
                        queues[part_key].put(row)

                    except:
                        failed_events += 1
                        print("events failed:", failed_events)

        for i in range(TARGET_QUEUES):
            queues[i].put("done")
            threads[i].join()
