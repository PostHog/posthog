import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Report Django migration metrics to Prometheus pushgateway"

    def add_arguments(self, parser):
        parser.add_argument(
            "--attempts",
            type=int,
            required=True,
            help="Number of migration attempts made",
        )
        parser.add_argument(
            "--success",
            action="store_true",
            help="Whether migration ultimately succeeded",
        )

    def handle(self, *args, **options):
        attempts = options["attempts"]
        success = options["success"]

        if not settings.PROM_PUSHGATEWAY_ADDRESS:
            logger.info("PROM_PUSHGATEWAY_ADDRESS not set, skipping metric push")
            return

        registry = CollectorRegistry()

        attempts_gauge = Gauge(
            "django_migration_attempts",
            "Number of attempts for the last Django migration run",
            registry=registry,
        )
        attempts_gauge.set(attempts)

        success_gauge = Gauge(
            "django_migration_success",
            "Whether the last Django migration succeeded (1) or failed (0)",
            registry=registry,
        )
        success_gauge.set(1 if success else 0)

        try:
            push_to_gateway(
                settings.PROM_PUSHGATEWAY_ADDRESS,
                job="django_migrate",
                registry=registry,
            )
            logger.info(
                "Pushed migration metrics",
                extra={"attempts": attempts, "success": success},
            )
        except Exception as e:
            logger.exception("Failed to push migration metrics", extra={"error": str(e)})
