from django.core.management.base import BaseCommand
import logging
import sys

from ee.support_sidebar_max.sidebar_max_AI import app

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Run Max's chat server"

    def add_arguments(self, parser):
        parser.add_argument(
            "--port",
            type=int,
            default=3001,
            help="Port to run the server on (default: 3001)",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="0.0.0.0",
            help="Host to bind to (default: 0.0.0.0)",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Run in debug mode",
        )

    def handle(self, *args, **options):
        port = options["port"]
        host = options["host"]
        debug = options["debug"]

        logger.info("Starting Max's chat server on port %d... 🦔", port)
        try:
            app.run(host=host, port=port, debug=debug)
        except KeyboardInterrupt:
            logger.info("\nShutting down Max's chat server... 👋")
            sys.exit(0)
        except Exception as e:
            logger.exception("\n\n🔴 Oops! Something went wrong: %s\n", str(e))
            sys.exit(1)
