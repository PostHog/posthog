from typing import Any

from django.core.management.base import BaseCommand, CommandError

from redbeat.schedulers import RedBeatConfig, get_redis
from redis.exceptions import RedisError

from posthog.celery import app
from posthog.redbeat_preflight import find_denials, report


class Command(BaseCommand):
    help = "Check that Redis allows every command the RedBeat beat scheduler needs"

    def handle(self, *args: Any, **options: Any) -> None:
        config = RedBeatConfig(app)
        try:
            client = get_redis(app)
            denials = find_denials(client, config.statics_key, config.key_prefix, config.lock_key)
        except RedisError as exc:
            # Whether Redis answers at all is beat's own problem to report.
            self.stderr.write(f"Skipped, Redis did not answer: {exc}")
            return

        if denials:
            raise CommandError(report(config.redis_url, config.key_prefix, denials))

        self.stdout.write("Redis allows every command the beat scheduler needs")
