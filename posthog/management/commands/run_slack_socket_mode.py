import signal
import sys
from django.core.management.base import BaseCommand, CommandError
from posthog.api.slack_socket_mode import SlackSocketModeClient
import structlog

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Run Slack Socket Mode client to handle real-time events and slash commands"

    def add_arguments(self, parser):
        parser.add_argument(
            "--app-token",
            type=str,
            help="Slack app-level token (overrides SLACK_APP_TOKEN setting)",
        )
        parser.add_argument(
            "--bot-token",
            type=str,
            help="Bot user OAuth token (overrides SLACK_BOT_TOKEN setting)",
        )

    def handle(self, *args, **options):
        app_token = options.get("app_token")
        bot_token = options.get("bot_token")

        # Create client from settings or command line arguments
        if app_token and bot_token:
            client = SlackSocketModeClient(app_token=app_token, bot_token=bot_token)
        else:
            client = SlackSocketModeClient.from_settings()

        if not client:
            raise CommandError(
                "Slack Socket Mode client could not be initialized. "
                "Please ensure SLACK_APP_TOKEN and SLACK_BOT_TOKEN are configured, "
                "or provide --app-token and --bot-token arguments."
            )

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            client.disconnect()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            self.stdout.write(self.style.SUCCESS("Starting Slack Socket Mode client..."))
            client.start()

            # Keep the main thread alive
            logger.info("Slack Socket Mode client is running. Press Ctrl+C to stop.")

            # Wait for the client to stay connected
            while True:
                try:
                    # Check if the client is still connected
                    if not client.socket_mode_client.is_connected():
                        logger.warning("Socket mode client disconnected, attempting to reconnect...")
                        client.start()

                    # Sleep to prevent busy waiting
                    import time

                    time.sleep(1)

                except KeyboardInterrupt:
                    break

        except Exception as e:
            logger.error(f"Error running Slack Socket Mode client: {e}", exc_info=True)
            raise CommandError(f"Failed to run Slack Socket Mode client: {e}")
        finally:
            self.stdout.write("Shutting down Slack Socket Mode client...")
            client.disconnect()
            self.stdout.write(self.style.SUCCESS("Slack Socket Mode client stopped."))
