import json

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from posthog.models.remote_config import RemoteConfig
from posthog.models.snippet_versioning import REDIS_LATEST_KEY, validate_version_artifacts
from posthog.storage import object_storage


class Command(BaseCommand):
    help = "Set the latest posthog-js version pointer. Validates artifacts exist before updating."

    def add_arguments(self, parser):
        parser.add_argument(
            "js_version",
            type=str,
            help="The version to set as latest (e.g. 1.359.0)",
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Purge CDN cache for posthog-js-latest tag (emergency use)",
        )

    def handle(self, *args, **options):
        version = options["js_version"]
        purge = options["purge"]

        if not settings.POSTHOG_JS_S3_BUCKET:
            raise CommandError("POSTHOG_JS_S3_BUCKET is not configured")

        # 1. Validate artifacts
        self.stdout.write(f"Validating artifacts for v{version}...")
        if not validate_version_artifacts(version):
            raise CommandError(
                f"Artifacts for v{version} not found in S3 bucket {settings.POSTHOG_JS_S3_BUCKET}. "
                f"Ensure posthog-js/v{version}/array.js exists before setting as latest."
            )
        self.stdout.write(self.style.SUCCESS("Artifacts validated"))

        # 2. Read existing pointers and update
        try:
            raw = object_storage.read(
                "posthog-js/latest.json",
                bucket=settings.POSTHOG_JS_S3_BUCKET,
                missing_ok=True,
            )
            pointers = json.loads(raw) if raw else {}
        except Exception:
            pointers = {}

        pointers["latest"] = version
        new_raw = json.dumps(pointers, sort_keys=True)

        # 3. Write to Redis (immediate effect)
        cache.set(REDIS_LATEST_KEY, new_raw, timeout=None)
        self.stdout.write(self.style.SUCCESS("Redis updated"))

        # 4. Write to S3 (durable)
        object_storage.write(
            "posthog-js/latest.json",
            new_raw,
            bucket=settings.POSTHOG_JS_S3_BUCKET,
        )
        self.stdout.write(self.style.SUCCESS("S3 updated"))

        # 5. Optional CDN purge
        if purge:
            self.stdout.write("Purging CDN cache for posthog-js-latest...")
            RemoteConfig.purge_cdn_by_tag("posthog-js-latest")
            self.stdout.write(self.style.SUCCESS("CDN purge triggered"))

        self.stdout.write(self.style.SUCCESS(f"Latest posthog-js version set to {version}"))
