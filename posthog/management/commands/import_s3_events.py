import csv
import json
import os
import re
import sys
import threading
from multiprocessing import Queue

from dateutil import parser
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from smart_open import smart_open

from posthog.celery import app as celery_app
from posthog.utils import is_clickhouse_enabled

IS_DRY_RUN = bool(os.environ.get("IS_DRY_RUN", False))


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
        parser.add_argument("--teamidlte", default=None)
        parser.add_argument("--teamidgt", default=None)

    def handle(self, *args, **options):
        if not options["bucketpath"]:
            print("The argument --bucket-path is required")
            exit(1)

        bucket_path = options["bucketpath"]

        files_to_read = os.environ.get("S3_IMPORT_FILES").split(",")

        ordered_files = []

        print(files_to_read)

        team_id_lte = int(options["teamidlte"]) if options["teamidlte"] else sys.maxsize
        team_id_gt = int(options["teamidgt"]) if options["teamidgt"] else 0

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
                        is_team_id_in_range = int(row[4]) > team_id_gt and int(row[4]) <= team_id_lte
                        if (
                            (len(team_ids) and row[4] not in team_ids)
                            or row[4] in team_ids_ignore
                            or not is_team_id_in_range
                        ):
                            print(is_team_id_in_range, row[4])
                            continue

                        print(row[5])
                        if is_clickhouse_enabled():
                            from posthog.api.capture import log_event

                            if IS_DRY_RUN:
                                print("KAFKA")
                                print(row)
                                return

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

                            if IS_DRY_RUN:
                                print("CELERY")
                                print(row)
                                return

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
                    except Exception as e:
                        print(e)
                        failed_events += 1
                        print("events failed:", failed_events)

                    # try:
                    #     with open("/tmp/uuids", "a") as f:
                    #         f.write(row[7] + "\n")
                    # except:
                    #     pass
