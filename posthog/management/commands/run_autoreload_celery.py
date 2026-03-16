import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from typing import Literal

from django.core.management.base import BaseCommand

import pywatchman

from posthog.tasks.utils import CeleryQueue

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Directories to watch for .py changes
WATCH_DIRS = ["posthog", "ee", "products"]

# Debounce: ignore changes within this window after a restart
DEBOUNCE_SECONDS = 2


class Command(BaseCommand):
    help = "Run Celery with watchman-based auto-reload (no fork overhead)"

    def add_arguments(self, parser):
        parser.add_argument("--type", type=str, choices=("worker", "beat"), help="Process type")
        parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")

    def handle(self, *args, **options):
        process_type: Literal["worker", "beat"] = options["type"]

        if options["no_reload"]:
            self._run_celery_inline(process_type)
            return

        self._run_with_watchman(process_type)

    def _build_celery_cmd(self, process_type: Literal["worker", "beat"]) -> list[str]:
        if process_type == "beat":
            return [
                sys.executable,
                "manage.py",
                "run_autoreload_celery",
                "--type=beat",
                "--no-reload",
            ]

        return [
            sys.executable,
            "manage.py",
            "run_autoreload_celery",
            "--type=worker",
            "--no-reload",
        ]

    def _run_celery_inline(self, process_type: Literal["worker", "beat"]):
        """Run celery directly in this process (no autoreload)."""
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

    def _run_with_watchman(self, process_type: Literal["worker", "beat"]):
        """Watch for .py changes via watchman and restart the celery subprocess."""
        client = pywatchman.client(timeout=5)
        root = str(PROJECT_ROOT)

        # Ensure watchman is watching the project root
        client.query("watch-project", root)

        # Subscribe to .py file changes in the relevant directories
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
                # Drop intermediate notifications — only need to know something changed
                "drop": ["stat"],
                "defer_vcs": True,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(f"Watching {', '.join(WATCH_DIRS)} for .py changes (celery {process_type})")
        )

        cmd = self._build_celery_cmd(process_type)
        proc = self._start_subprocess(cmd)
        last_restart = time.monotonic()

        try:
            while True:
                # Block until watchman has data (1s timeout to check subprocess health)
                try:
                    client.receive()
                except pywatchman.SocketTimeout:
                    # Check if subprocess died on its own
                    if proc.poll() is not None:
                        self.stderr.write(
                            self.style.WARNING(
                                f"Celery {process_type} exited with code {proc.returncode}, restarting..."
                            )
                        )
                        proc = self._start_subprocess(cmd)
                        last_restart = time.monotonic()
                    continue

                # Get subscription notifications
                data = client.getSubscription(sub_name)
                if not data:
                    continue

                # Debounce
                now = time.monotonic()
                if now - last_restart < DEBOUNCE_SECONDS:
                    continue

                # Collect changed file names for logging
                changed = set()
                for notification in data:
                    changed.update(notification.get("files", []))

                if not changed:
                    continue

                sample = list(changed)[:3]
                suffix = f" (+{len(changed) - 3} more)" if len(changed) > 3 else ""
                self.stdout.write(
                    self.style.WARNING(
                        f"Change detected: {', '.join(sample)}{suffix} — restarting celery {process_type}"
                    )
                )

                self._stop_subprocess(proc)
                proc = self._start_subprocess(cmd)
                last_restart = time.monotonic()

        except KeyboardInterrupt:
            pass
        finally:
            self._stop_subprocess(proc)
            try:
                client.query("unsubscribe", root, sub_name)
            except Exception:
                pass

    def _start_subprocess(self, cmd: list[str]) -> subprocess.Popen:
        return subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))

    def _stop_subprocess(self, proc: subprocess.Popen):
        if proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
