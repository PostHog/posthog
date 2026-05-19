import os
import asyncio
import logging
import dataclasses
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.hogql.service import HogQLPostgresServer, HogQLServiceConfig

logger = logging.getLogger("posthog.hogql.service")


class Command(BaseCommand):
    help = "Run the HogQL Postgres wire-compatible service"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--host", default=None, help="Host to bind. Defaults to HOGQL_SERVICE_HOST or 127.0.0.1.")
        parser.add_argument(
            "--port", type=int, default=None, help="Port to bind. Defaults to HOGQL_SERVICE_PORT or 6543."
        )
        parser.add_argument(
            "--shared-secret",
            default=None,
            help="Shared secret for impersonation auth. Defaults to HOGQL_SERVICE_SHARED_SECRET.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        log_file = os.environ.get("HOGQL_SERVICE_LOG_FILE", "/tmp/posthog-hogql-service.log")
        self._configure_file_logging(log_file)

        config = HogQLServiceConfig.from_env()
        if options["host"] is not None:
            config = dataclasses.replace(config, host=options["host"])
        if options["port"] is not None:
            config = dataclasses.replace(config, port=options["port"])
        if options["shared_secret"] is not None:
            config = dataclasses.replace(config, shared_secret=options["shared_secret"])

        self.stdout.write(f"Starting HogQL service on {config.host}:{config.port}")
        self.stdout.write(f"HogQL service logs: {log_file}")
        self._write_log_line(log_file, f"Starting HogQL service on {config.host}:{config.port}")
        logger.info("Starting HogQL service", extra={"hogql_service_log_file": log_file})
        asyncio.run(HogQLPostgresServer(config, on_listening=self.stdout.write).serve_forever())

    def _configure_file_logging(self, log_file: str) -> None:
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler) and handler.baseFilename == log_file:
                return

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(file_handler)
        logger.disabled = False
        logger.setLevel(logging.INFO)

    def _write_log_line(self, log_file: str, message: str) -> None:
        with open(log_file, "a") as file:
            file.write(f"{message}\n")
