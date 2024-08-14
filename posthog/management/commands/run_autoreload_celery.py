from typing import Literal
import django
from django.core.management.base import BaseCommand

from posthog.tasks.utils import CeleryQueue

# ❗ needs to be called *before* importing autoreload
django.setup()

from django.utils import autoreload  # noqa: E402


class Command(BaseCommand):
    help = "Run Celery wrapped in Django's auto-reload feature"

    def add_arguments(self, parser):
        parser.add_argument("--type", type=str, choices=("worker", "beat"), help="Process type")

    def handle(self, *args, **options):
        autoreload.run_with_reloader(lambda: self.run_celery_worker(options["type"]))

    @staticmethod
    def run_celery_worker(type: Literal["worker", "beat"]):
        from posthog.celery import app as celery_app

        args = (
            [
                "-A",
                "posthog",
                "worker",
                "--pool=threads",
                f"--queues={','.join(q.value for q in CeleryQueue)}",
            ]
            if type == "worker"
            else [
                "-A",
                "posthog",
                "beat",
                "--scheduler",
                "redbeat.RedBeatScheduler",
            ]
        )

        celery_app.worker_main(args)
