import signal
import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("orchestra")


class Command(BaseCommand):
    help = "Start the Orchestra workflow engine worker"

    def add_arguments(self, parser):
        parser.add_argument(
            "--task-queue",
            default="default",
            help="Task queue to poll (default: 'default')",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=None,
            help="Number of concurrent pollers",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=None,
            help="Seconds between polls when idle",
        )

    def handle(self, *args, **options):
        import products.orchestra.backend.demo.greeting  # noqa: F401 — registers @execution/@step

        task_queue = options["task_queue"]
        concurrency = options["concurrency"] or settings.ORCHESTRA_MAX_CONCURRENCY
        poll_interval = options["poll_interval"] or settings.ORCHESTRA_POLL_INTERVAL
        dsn = settings.ORCHESTRA_DSN

        logger.info(
            "Starting Orchestra worker: queue=%s concurrency=%d poll_interval=%.1f",
            task_queue,
            concurrency,
            poll_interval,
        )

        asyncio.run(
            self._run_worker(
                dsn=dsn,
                task_queue=task_queue,
                concurrency=concurrency,
                poll_interval=poll_interval,
                lease_seconds=settings.ORCHESTRA_LEASE_SECONDS,
            )
        )

    async def _run_worker(
        self,
        *,
        dsn: str,
        task_queue: str,
        concurrency: int,
        poll_interval: float,
        lease_seconds: int,
    ) -> None:
        from products.orchestra.backend.engine import Database, Worker

        db = await Database.connect(dsn)
        worker = Worker(
            db,
            task_queue,
            lease_seconds=lease_seconds,
            concurrency=concurrency,
            poll_interval=poll_interval,
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, worker.stop)

        try:
            await worker.run()
        finally:
            await db.close()
            logger.info("Orchestra worker shut down")
