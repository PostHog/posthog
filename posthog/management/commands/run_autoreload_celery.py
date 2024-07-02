import django

from django.core.management.base import BaseCommand

from posthog.tasks.utils import CeleryQueue

# ❗ needs to be called *before* importing autoreload
django.setup()

from django.utils import autoreload  # noqa: E402


class Command(BaseCommand):
    help = "Wrap celery in djangos auto reload functionality"

    def add_arguments(self, parser):
        parser.add_argument("celery_type", type=str, help="worker or heartbeat")

    def handle(self, *args, **options):
        celery_type = options.get("celery_type")

        if celery_type == "worker":
            print("Starting celery worker with autoreload...")  # noqa: T201
            autoreload.run_with_reloader(self.run_celery_worker)
        elif celery_type == "heartbeat":
            print("Starting celery heartbeat with autoreload...")  # noqa: T201
            autoreload.run_with_reloader(self.run_celery_heartbeat)
        else:
            raise Exception("Celery type invalid")

    def run_celery_worker(self):
        from posthog.celery import app as celery_app

        queues = [q.value for q in CeleryQueue]

        args = [
            "-A",
            "posthog",
            "worker",
            "--without-heartbeat",
            "--without-mingle",
            "--pool=threads",
            f"--queues={','.join(queues)}",
            "-Ofair",
            "-n",
            "node@%h",
        ]

        celery_app.worker_main(args)

    def run_celery_heartbeat(self):
        from posthog.celery import app as celery_app

        args = ["-A", "posthog", "beat", "-S", "redbeat.RedBeatScheduler"]

        celery_app.worker_main(args)
