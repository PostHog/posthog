import signal
from django.core.management.base import BaseCommand
from posthog.api.slack_socket_mode import SlackSocketModeClient
import structlog

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Run Slack Socket Mode client to handle real-time events and slash commands"

    def __init__(self):
        super().__init__()

    def handle(self, *args, **options):
        client = SlackSocketModeClient()

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            self.stdout.write("Shutting down Slack Socket Mode client...")
            client.close()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.stdout.write("Starting Slack Socket Mode client...")
        client.connect()
        self.stdout.write(self.style.SUCCESS("Slack Socket Mode client is running. Press Ctrl+C to stop."))
        # Wait for the client to stay connected
        client.socket_mode_client.current_app_monitor.thread.join()
