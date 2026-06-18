import json
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from posthog.models.js_snippet_versioning import (
    REDIS_POINTER_MAP_KEY,
    S3_MANIFEST_KEY,
    S3_VERSIONS_KEY,
    ManifestSyncError,
    VersionEntry,
    VersionManifest,
    array_js_path,
    changed_pointers,
    compute_version_manifest,
    purge_changed_pointers,
    s3_read,
    s3_write,
    sync_manifest_from_s3,
    validate_version_artifacts,
)

# Usage:
#
#   # Preview what publishing a version would change (dry-run, no writes):
#   ./manage.py js_snippet_version publish 1.359.0
#
#   # Actually publish (writes to S3 manifest + Redis pointer map):
#   ./manage.py js_snippet_version publish 1.359.0 --accept
#
#   # Publish and purge affected CDN cache tags:
#   ./manage.py js_snippet_version publish 1.359.0 --accept --purge
#
#   # Yank a bad version (soft-delete, pointer map falls back to previous):
#   ./manage.py js_snippet_version yank 1.359.0 --accept --purge
#
#   # Re-sync versions.json from S3 to Redis (same as celery task):
#   ./manage.py js_snippet_version sync


class Command(BaseCommand):
    help = "Manage posthog-js version manifest (publish new versions, yank existing ones). Dry-run by default."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="action", required=True)

        for name, help_text in [("publish", "Publish a new version"), ("yank", "Yank (soft-delete) a version")]:
            sub = subparsers.add_parser(name, help=help_text)
            sub.add_argument("version", type=str, help="Version (e.g. 1.359.0)")
            sub.add_argument("--accept", action="store_true", help="Actually write changes (default is dry-run)")
            sub.add_argument("--purge", action="store_true", help="Purge CDN cache for affected versions")

        subparsers.add_parser("sync", help="Re-sync versions.json from S3 to Redis")

    def handle(self, *args, **options):
        if not settings.POSTHOG_JS_S3_BUCKET:
            raise CommandError("POSTHOG_JS_S3_BUCKET is not configured")

        action = options["action"]
        if action == "publish":
            self._handle_publish(options)
        elif action == "yank":
            self._handle_yank(options)
        elif action == "sync":
            self._handle_sync()

    def _read_manifest(self) -> list[VersionEntry]:
        try:
            raw = s3_read(S3_VERSIONS_KEY, missing_ok=True)
            return json.loads(raw) if raw else []
        except Exception:
            return []

    def _write_manifest(self, entries: list[VersionEntry]) -> None:
        raw = json.dumps(entries, indent=2)
        s3_write(S3_VERSIONS_KEY, raw)
        self.stdout.write(self.style.SUCCESS("S3 updated"))

    def _update_redis(self, manifest: VersionManifest) -> None:
        manifest_json = json.dumps(manifest)
        cache.set(REDIS_POINTER_MAP_KEY, manifest_json, timeout=None)
        self.stdout.write(self.style.SUCCESS(f"Redis updated with manifest: {manifest}"))

        # Write validated manifest backup to S3 so that _recover_manifest_from_s3
        # can restore from it if Redis is flushed before the next periodic sync.
        s3_write(S3_MANIFEST_KEY, manifest_json)
        self.stdout.write(self.style.SUCCESS("S3 manifest backup updated"))

    def _purge_changed(self, before: dict[str, str], after: dict[str, str]) -> None:
        changed = purge_changed_pointers(before, after)
        if not changed:
            self.stdout.write("No pointers changed, nothing to purge")
            return
        for pointer in sorted(changed):
            self.stdout.write(f"Purged CDN cache for posthog-js-{pointer}")
        self.stdout.write(self.style.SUCCESS(f"CDN purge triggered for {len(changed)} pointer(s)"))

    def _print_diff(self, before: dict[str, str], after: dict[str, str]) -> None:
        changed = changed_pointers(before, after)
        if not changed:
            self.stdout.write("No pointer changes")
            return
        self.stdout.write("Pointer changes:")
        for pointer in sorted(changed):
            old = before.get(pointer, "(none)")
            new = after.get(pointer, "(none)")
            self.stdout.write(f"  {pointer}: {old} -> {new}")

    def _handle_publish(self, options: dict) -> None:
        version = options["version"]
        accept = options.get("accept", False)

        # Validate artifacts exist
        self.stdout.write(f"Validating artifacts for v{version}...")
        if not validate_version_artifacts(version):
            raise CommandError(
                f"Artifacts for v{version} not found in S3 bucket {settings.POSTHOG_JS_S3_BUCKET}. "
                f"Ensure {array_js_path(version)} exists before publishing."
            )
        self.stdout.write(self.style.SUCCESS("Artifacts validated"))

        entries = self._read_manifest()
        before = compute_version_manifest(entries)

        # Check for duplicate
        if any(e["version"] == version for e in entries):
            raise CommandError(f"Version {version} already exists in the manifest")

        entries.append(
            {
                "version": version,
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

        after = compute_version_manifest(entries)
        self._print_diff(before["pointers"], after["pointers"])

        if not accept:
            self.stdout.write(self.style.WARNING("Dry-run mode. Pass --accept to write changes."))
            return

        self._write_manifest(entries)
        self._update_redis(after)

        if options.get("purge"):
            self._purge_changed(before["pointers"], after["pointers"])

        self.stdout.write(self.style.SUCCESS(f"Published posthog-js v{version}"))

    def _handle_yank(self, options: dict) -> None:
        version = options["version"]
        accept = options.get("accept", False)
        entries = self._read_manifest()
        before = compute_version_manifest(entries)

        found = False
        for entry in entries:
            if entry["version"] == version:
                entry["yanked"] = True
                found = True
                break

        if not found:
            raise CommandError(f"Version {version} not found in the manifest")

        after = compute_version_manifest(entries)
        self._print_diff(before["pointers"], after["pointers"])

        if not accept:
            self.stdout.write(self.style.WARNING("Dry-run mode. Pass --accept to write changes."))
            return

        self._write_manifest(entries)
        self._update_redis(after)

        if options.get("purge"):
            self._purge_changed(before["pointers"], after["pointers"])

        self.stdout.write(self.style.SUCCESS(f"Yanked posthog-js v{version}"))

    def _handle_sync(self) -> None:
        try:
            manifest = sync_manifest_from_s3()
        except ManifestSyncError as e:
            raise CommandError(str(e))

        self.stdout.write(f"Versions: {len(manifest['versions'])}")
        self.stdout.write(f"Pointers: {manifest['pointers']}")
        self.stdout.write(self.style.SUCCESS("Sync complete"))
