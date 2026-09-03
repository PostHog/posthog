from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.management.desktop_feature_flag_sync import sync_desktop_feature_flags


class Command(BaseCommand):
    help = "Add and enable PostHog Desktop feature flags for local development"

    def handle(self, *args: object, **options: object) -> None:
        if settings.CLOUD_DEPLOYMENT or not settings.DEBUG:
            raise CommandError("sync_desktop_feature_flags is only available in local development.")

        sync_desktop_feature_flags(self.stdout.write)
