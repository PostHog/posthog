from django.core.management.base import BaseCommand

from posthog.tasks.remote_config import sync_all_remote_configs


class Command(BaseCommand):
    help = "Sync all RemoteConfigs"

    def handle(self, *args, **options):
        print("Syncing RemoteConfigs for all teams...")  # noqa: T201
        sync_all_remote_configs()
        print("All syncs scheduled")  # noqa: T201
