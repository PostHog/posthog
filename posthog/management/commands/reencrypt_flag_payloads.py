from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import QuerySet

import structlog
from cryptography.fernet import InvalidToken

from products.feature_flags.backend.encrypted_flag_payloads import FlagPayloadCodec, flag_payload_codec
from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Re-encrypt remote-config feature flag payloads with the primary key in FLAGS_SECRET_KEYS. "
        "Run after prepending a new key to FLAGS_SECRET_KEYS (keeping the old key in the list) "
        "and before dropping the old key from FLAGS_SECRET_KEYS. Safe to re-run; idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--limit", default=None, type=int, help="Process at most this many flags")
        parser.add_argument("--batch-size", default=100, type=int, help="DB iterator chunk size")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args, **options) -> None:
        live_run: bool = options["live_run"]
        team_id: int | None = options["team_id"]
        limit: int | None = options["limit"]
        batch_size: int = options["batch_size"]

        # rotate() decrypts with any key in FLAGS_SECRET_KEYS, then re-encrypts
        # with the primary (first) key — exactly the re-encryption we need.
        codec = flag_payload_codec()

        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting reencrypt_flag_payloads ({mode})")

        scanned = updated = skipped = 0
        for flag in self._get_flags(team_id, limit).iterator(chunk_size=batch_size):
            scanned += 1
            try:
                changed = self._reencrypt(flag.pk, codec) if live_run else self._needs_reencrypt(flag, codec)
            except InvalidToken as e:
                # A payload no key can decrypt (corrupt, or already-plaintext). Skip
                # the whole flag rather than write a half-rotated payloads dict.
                # Narrow to InvalidToken so DB and programming errors propagate
                # instead of being silently counted as skips on a "successful" run.
                skipped += 1
                logger.warning(
                    "reencrypt_flag_payloads.skip", flag_id=flag.id, team_id=flag.team_id, error=str(e), exc_info=True
                )
                self.stderr.write(f"  ! skipped flag {flag.id} (team {flag.team_id}): {e}")
                continue
            if changed:
                updated += 1

        verb = "re-encrypted" if live_run else "would re-encrypt"
        self.stdout.write(f"Done. scanned={scanned} {verb}={updated} skipped={skipped}")

    def _needs_reencrypt(self, flag: FeatureFlag, codec: FlagPayloadCodec) -> bool:
        """Dry-run check on the streamed snapshot: would this flag's payloads be rotated?"""
        payloads = (flag.filters or {}).get("payloads") or {}
        return self._rotate_payloads(payloads, codec) is not None

    def _reencrypt(self, flag_pk: int, codec: FlagPayloadCodec) -> bool:
        """Rotate one flag's payloads under a row lock, returning True if anything changed.

        Re-read ``filters`` inside the lock so we merge the rotation into the current
        value rather than a stale streamed snapshot — otherwise a concurrent edit to
        other filter fields between the scan and the write would be silently lost.
        """
        with transaction.atomic():
            flag = FeatureFlag.objects.select_for_update().only("id", "filters").get(pk=flag_pk)
            filters = flag.filters or {}
            rotated = self._rotate_payloads(filters.get("payloads") or {}, codec)
            if rotated is None:
                return False
            # update() rather than save(): plaintext is unchanged, so we want no
            # activity-log entry and no cache churn (these flags are excluded from
            # the flags cache and the /remote_config endpoint reads live from the DB).
            FeatureFlag.objects.filter(pk=flag_pk).update(filters={**filters, "payloads": rotated})
            return True

    def _rotate_payloads(self, payloads: dict, codec: FlagPayloadCodec) -> dict | None:
        """Return rotated payloads, or None when there is nothing to do.

        None means every payload already decrypts on the primary key, so rotating
        would only churn ciphertext without advancing the migration. Raises
        InvalidToken if a payload cannot be decrypted by any key (corrupt or
        already-plaintext).
        """
        if not payloads or all(codec.is_encrypted_with_primary(v.encode("utf-8")) for v in payloads.values()):
            return None
        return {key: codec.rotate(value.encode("utf-8")).decode("utf-8") for key, value in payloads.items()}

    def _get_flags(self, team_id: int | None, limit: int | None) -> QuerySet[FeatureFlag]:
        flags = FeatureFlag.objects.filter(has_encrypted_payloads=True).only("id", "team_id", "filters").order_by("id")
        if team_id is not None:
            flags = flags.filter(team_id=team_id)
        if limit is not None:
            flags = flags[:limit]
        return flags
