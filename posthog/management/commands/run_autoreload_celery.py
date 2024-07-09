import django

from django.core.management.base import BaseCommand

from posthog.tasks.utils import CeleryQueue

# ❗ needs to be called *before* importing autoreload
django.setup()

from django.utils import autoreload  # noqa: E402


class Command(BaseCommand):
    help = "Wrap celery in djangos auto reload functionality"

    def handle(self, *args, **options):
        autoreload.run_with_reloader(self.run_celery_worker)

    def run_celery_worker(self):
        from posthog.celery import app as celery_app

        queues = [q.value for q in CeleryQueue]

        args = [
            "-A",
            "posthog",
            "worker",
            "-B",
            "--pool=threads",
            f"--queues={','.join(queues)}",
            "-Ofair",
            "-n",
            "node@%h",
        ]

        celery_app.worker_main(args)
