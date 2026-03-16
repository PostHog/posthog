import os
import sys
import threading
from pathlib import Path
from typing import Literal

from django.core.management.base import BaseCommand

import pywatchman

from posthog.tasks.utils import CeleryQueue

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Directories to watch for .py changes
WATCH_DIRS = ["posthog", "ee", "products"]


class Command(BaseCommand):
    help = "Run Celery with watchman-based auto-reload"

    def add_arguments(self, parser):
        parser.add_argument("--type", type=str, choices=("worker", "beat"), help="Process type")
        parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")

    def handle(self, *args, **options):
        process_type: Literal["worker", "beat"] = options["type"]

        if not options["no_reload"]:
            self._start_watchman_thread(process_type)

        self._run_celery(process_type)

    def _run_celery(self, process_type: Literal["worker", "beat"]):
        from posthog.celery import app as celery_app

        if process_type == "beat":
            celery_app.start(argv=["beat", "--scheduler", "redbeat.RedBeatScheduler"])
        else:
            celery_app.worker_main(
                argv=[
                    "-A",
                    "posthog",
                    "worker",
                    "--pool=threads",
                    f"--queues={','.join(q.value for q in CeleryQueue)}",
                ]
            )

    def _start_watchman_thread(self, process_type: Literal["worker", "beat"]):
        """Start a background thread that watches for .py changes and re-execs the process."""
        thread = threading.Thread(
            target=self._watchman_loop,
            args=(process_type,),
            daemon=True,
        )
        thread.start()

    def _watchman_loop(self, process_type: Literal["worker", "beat"]):
        try:
            client = pywatchman.client(timeout=5)
            root = str(PROJECT_ROOT)
            client.query("watch-project", root)
        except (pywatchman.WatchmanError, pywatchman.CommandError, ConnectionError, OSError) as e:
            self.stderr.write(self.style.WARNING(f"Watchman not available, auto-reload disabled: {e}"))
            return

        sub_name = f"celery-reload-{process_type}-{os.getpid()}"
        client.query(
            "subscribe",
            root,
            sub_name,
            {
                "expression": [
                    "allof",
                    ["suffix", "py"],
                    [
                        "anyof",
                        *[["dirname", d] for d in WATCH_DIRS],
                    ],
                    ["not", ["dirname", "__pycache__"]],
                    ["not", ["match", "*/migrations/*"]],
                ],
                "fields": ["name"],
                "drop": ["stat"],
                "defer_vcs": True,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(f"Watching {', '.join(WATCH_DIRS)} for .py changes (celery {process_type})")
        )

        # Skip initial notification from subscription setup — watchman sends the
        # current state of matching files immediately upon subscribing
        try:
            client.receive()
            client.getSubscription(sub_name)
        except pywatchman.SocketTimeout:
            pass

        while True:
            try:
                client.receive()
            except pywatchman.SocketTimeout:
                continue

            data = client.getSubscription(sub_name)
            if not data:
                continue

            changed: set[str] = set()
            for notification in data:
                changed.update(notification.get("files", []))

            if not changed:
                continue

            sample = list(changed)[:3]
            suffix = f" (+{len(changed) - 3} more)" if len(changed) > 3 else ""
            self.stdout.write(
                self.style.WARNING(f"Change detected: {', '.join(sample)}{suffix} — restarting celery {process_type}")
            )

            # Re-exec the entire process — replaces this process in-place.
            # nosemgrep: python.lang.security.audit.dangerous-os-exec-tainted-env-args.dangerous-os-exec-tainted-env-args
            os.execv(sys.executable, [sys.executable, *sys.argv])
