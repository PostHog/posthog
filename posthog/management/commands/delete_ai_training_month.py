from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.ai_training_privacy import AITrainingPrivacyStore
from posthog.ai_training_privacy_reader import KEY_READ_LEASE_SECONDS


class Command(BaseCommand):
    help = "Permanently block an ML session month and remove its session and image keys."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("session_month", help="UTC session start month, in YYYY-MM format")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.AI_RESEARCH_REPLAY_PRIVACY_TABLE:
            raise CommandError("AI_RESEARCH_REPLAY_PRIVACY_TABLE is not configured")
        try:
            count = AITrainingPrivacyStore.from_settings().delete_month(options["session_month"])
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f"Removed {count} indexed keys. Existing read leases expire within {KEY_READ_LEASE_SECONDS} seconds."
        )
