import asyncio
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.hogql.service import HogQLPostgresServer, HogQLServiceConfig


class Command(BaseCommand):
    help = "Run the HogQL Postgres wire-compatible service"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--host", default=None, help="Host to bind. Defaults to HOGQL_SERVICE_HOST or 0.0.0.0.")
        parser.add_argument(
            "--port", type=int, default=None, help="Port to bind. Defaults to HOGQL_SERVICE_PORT or 6543."
        )
        parser.add_argument(
            "--shared-secret",
            default=None,
            help="Shared secret for impersonation auth. Defaults to HOGQL_SERVICE_SHARED_SECRET.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        config = HogQLServiceConfig.from_env()
        if options["host"] is not None:
            config = HogQLServiceConfig(
                host=options["host"],
                port=config.port,
                shared_secret=config.shared_secret,
                max_query_bytes=config.max_query_bytes,
            )
        if options["port"] is not None:
            config = HogQLServiceConfig(
                host=config.host,
                port=options["port"],
                shared_secret=config.shared_secret,
                max_query_bytes=config.max_query_bytes,
            )
        if options["shared_secret"] is not None:
            config = HogQLServiceConfig(
                host=config.host,
                port=config.port,
                shared_secret=options["shared_secret"],
                max_query_bytes=config.max_query_bytes,
            )

        self.stdout.write(f"Starting HogQL service on {config.host}:{config.port}")
        asyncio.run(HogQLPostgresServer(config, on_listening=self.stdout.write).serve_forever())
