import json
import base64
import binascii
from dataclasses import (
    dataclass,
    field as dataclass_field,
)

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, router

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from posthog.helpers.encrypted_fields import EncryptedFieldMixin

# Read-only audit that answers a single question before a SECRET_KEY rotation: is any encrypted-field
# value still decryptable *only* by a SECRET_KEY-derived legacy key? Those rows would be permanently
# stranded the moment the old key leaves SECRET_KEY / SECRET_KEY_FALLBACKS. New writes use
# ENCRYPTION_SALT_KEYS[0]; the SECRET_KEY-derived keys are a decrypt-only fallback for pre-rework data.

# Per-row classifications. Only LEGACY blocks dropping the old key; the rest are informational.
CLEAN = "clean"  # every token decrypts under ENCRYPTION_SALT_KEYS — unaffected by rotation
LEGACY = "legacy"  # at least one token decrypts only under a SECRET_KEY-derived key
PLAINTEXT = "plaintext"  # a leaf was never a Fernet token — stored unencrypted
UNREADABLE = "unreadable"  # token-shaped but no configured key decrypts it (wrong/lost key, or corrupt)
EMPTY = "empty"  # no meaningful value to classify (NULL, "", {}, [])

# jsonb leaves that carry no secret — an EncryptedJSONField with an empty value serializes to these
_EMPTY_MARKERS = frozenset({"", "{}", "[]", "null"})

# A Fernet token is urlsafe-base64 of >= 73 bytes whose first (version) byte is 0x80
_FERNET_VERSION = 0x80
_FERNET_MIN_BYTES = 73


@dataclass
class FieldReport:
    label: str
    scanned: int = 0
    counts: dict[str, int] = dataclass_field(
        default_factory=lambda: {CLEAN: 0, LEGACY: 0, PLAINTEXT: 0, UNREADABLE: 0, EMPTY: 0}
    )
    samples: dict[str, list[str]] = dataclass_field(default_factory=dict)
    error: str | None = None


def _salt_only_fernet() -> MultiFernet | None:
    keys = [base64.urlsafe_b64encode(x.encode("utf-8")) for x in settings.ENCRYPTION_SALT_KEYS]
    return MultiFernet([Fernet(k) for k in keys]) if keys else None


def _legacy_fernet() -> MultiFernet | None:
    # Mirrors the SECRET_KEY-derived branch of EncryptedFieldMixin.keys (SECRET_KEY + every fallback)
    keys = []
    for secret_key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]:
        for salt_key in settings.SALT_KEY:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt_key.encode("utf-8"),
                iterations=100000,
                backend=default_backend(),
            )
            keys.append(base64.urlsafe_b64encode(kdf.derive(secret_key.encode("utf-8"))))
    return MultiFernet([Fernet(k) for k in keys]) if keys else None


def _leaves(value: object) -> list[str]:
    # An EncryptedJSONField stores a token per leaf; scalar / JSON-string fields store a single token.
    # Callers must hand jsonb columns over as already-parsed dicts/lists (see Command._coerce_raw) —
    # Django's psycopg setup returns jsonb as a JSON *string* from a raw cursor, which would otherwise
    # be misread here as one opaque leaf.
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in _leaves(v)]
    if isinstance(value, list):
        return [leaf for v in value for leaf in _leaves(v)]
    return []


def _looks_like_fernet_token(value: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("utf-8"))
    except (binascii.Error, ValueError):
        return False
    return len(decoded) >= _FERNET_MIN_BYTES and decoded[0] == _FERNET_VERSION


def _decryptable(fernet: MultiFernet | None, token: str) -> bool:
    if fernet is None:
        return False
    try:
        fernet.decrypt(token.encode("utf-8"))
        return True
    except (InvalidToken, ValueError, TypeError):
        return False


def _classify_leaf(leaf: str, salt_only: MultiFernet | None, legacy: MultiFernet | None) -> str:
    if not _looks_like_fernet_token(leaf):
        return PLAINTEXT
    if _decryptable(salt_only, leaf):
        return CLEAN
    if _decryptable(legacy, leaf):
        return LEGACY
    return UNREADABLE


def classify(raw: object, salt_only: MultiFernet | None, legacy: MultiFernet | None) -> str:
    leaves = [leaf for leaf in _leaves(raw) if leaf not in _EMPTY_MARKERS]
    if not leaves:
        return EMPTY

    # Classify per leaf, then collapse to the row's most severe leaf. LEGACY must win over PLAINTEXT /
    # UNREADABLE: a single legacy-encrypted leaf is stranded on rotation, so a row containing one must
    # count as LEGACY even if a sibling leaf is plaintext — otherwise `safe_to_drop_secret_key` could
    # report true while legacy tokens are still present. CLEAN only when every leaf is clean.
    buckets = {_classify_leaf(leaf, salt_only, legacy) for leaf in leaves}
    for bucket in (LEGACY, UNREADABLE, PLAINTEXT):
        if bucket in buckets:
            return bucket
    return CLEAN


class Command(BaseCommand):
    help = (
        "Audit every Fernet-encrypted DB field and report which rows still depend on a SECRET_KEY-derived "
        "legacy key. Read-only. Run before rotating SECRET_KEY; a clean run (0 legacy rows) means the old "
        "key can be safely dropped from SECRET_KEY / SECRET_KEY_FALLBACKS."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--field",
            metavar="app_label.Model.field",
            help="Audit only this field instead of every discovered encrypted field",
        )
        parser.add_argument("--batch-size", type=int, default=1000, help="Rows fetched per DB round-trip")
        parser.add_argument("--limit", type=int, default=0, help="Max rows to scan per field (0 = all)")
        parser.add_argument("--samples", type=int, default=5, help="Sample pks to record per flagged class")
        parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report instead")

    def handle(self, *args, **options):
        salt_only = _salt_only_fernet()
        legacy = _legacy_fernet()
        if salt_only is None:
            raise CommandError("ENCRYPTION_SALT_KEYS is empty — nothing can be classified as clean")

        all_fields = self._discover_fields()
        if not all_fields:
            raise CommandError("No encrypted fields found")

        only = options.get("field")
        fields = [(m, f) for m, f in all_fields if only is None or self._label(m, f) == only]
        if only and not fields:
            available = "\n  ".join(sorted(self._label(m, f) for m, f in all_fields))
            raise CommandError(f"--field {only!r} did not match any encrypted field. Available:\n  {available}")

        reports = [self._audit_field(model, model_field, salt_only, legacy, options) for model, model_field in fields]

        if options["json"]:
            self._emit_json(reports)
        else:
            self._emit_console(reports)

    @staticmethod
    def _label(model, model_field) -> str:
        return f"{model._meta.app_label}.{model.__name__}.{model_field.name}"

    def _discover_fields(self):
        discovered = []
        for model in apps.get_models():
            if model._meta.proxy:
                continue
            for model_field in model._meta.concrete_fields:
                if isinstance(model_field, EncryptedFieldMixin):
                    discovered.append((model, model_field))
        return discovered

    def _audit_field(self, model, model_field, salt_only, legacy, options) -> FieldReport:
        report = FieldReport(label=self._label(model, model_field))
        samples = options["samples"]

        connection = connections[router.db_for_read(model)]
        quote = connection.ops.quote_name
        table, column, pk_column = model._meta.db_table, model_field.column, model._meta.pk.column

        # Only EncryptedJSONField is a jsonb column (per-leaf tokens); every other encrypted field is a
        # text column holding a single token. A raw cursor returns jsonb as a JSON string under Django's
        # psycopg config, so those rows need parsing before their leaves can be classified individually.
        is_json_column = model_field.get_internal_type() == "JSONField"

        cursor = connection.cursor()
        try:
            for pk, raw in self._iter_rows(cursor, quote, table, column, pk_column, options):
                report.scanned += 1
                bucket = classify(self._coerce_raw(raw, is_json_column), salt_only, legacy)
                report.counts[bucket] += 1
                if bucket in (LEGACY, PLAINTEXT, UNREADABLE):
                    pks = report.samples.setdefault(bucket, [])
                    if len(pks) < samples:
                        pks.append(str(pk))
        except Exception as exc:  # missing table on a partially-migrated DB, permission issues, etc.
            report.error = str(exc)
        finally:
            cursor.close()
        return report

    @staticmethod
    def _coerce_raw(raw: object, is_json_column: bool) -> object:
        # A raw cursor hands jsonb back as a JSON string (Django parses jsonb itself in JSONField),
        # so decode it into the dict/list whose leaves carry the per-leaf tokens. NULL stays None.
        # The isinstance guard keeps this correct if a backend ever returns jsonb already parsed.
        if is_json_column and isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw
        return raw

    def _iter_rows(self, cursor, quote, table, column, pk_column, options):
        batch_size, limit = options["batch_size"], options["limit"]
        last_pk, fetched = None, 0
        select = f"SELECT {quote(pk_column)}, {quote(column)} FROM {quote(table)}"
        while True:
            if last_pk is None:
                cursor.execute(f"{select} ORDER BY {quote(pk_column)} LIMIT %s", [batch_size])
            else:
                cursor.execute(
                    f"{select} WHERE {quote(pk_column)} > %s ORDER BY {quote(pk_column)} LIMIT %s",
                    [last_pk, batch_size],
                )
            rows = cursor.fetchall()
            if not rows:
                return
            for pk, raw in rows:
                yield pk, raw
                last_pk = pk
                fetched += 1
                if limit and fetched >= limit:
                    return

    def _emit_json(self, reports):
        payload = {
            "safe_to_drop_secret_key": all(r.counts[LEGACY] == 0 and r.error is None for r in reports),
            "fields": [r.__dict__ for r in reports],
        }
        self.stdout.write(json.dumps(payload, indent=2))

    def _emit_console(self, reports):
        total_legacy = sum(r.counts[LEGACY] for r in reports)
        total_plaintext = sum(r.counts[PLAINTEXT] for r in reports)
        total_unreadable = sum(r.counts[UNREADABLE] for r in reports)

        for r in sorted(reports, key=lambda x: x.label):
            if r.error:
                self.stdout.write(self.style.WARNING(f"  SKIP {r.label}: {r.error}"))
                continue
            c = r.counts
            style = self.style.ERROR if c[LEGACY] else self.style.SUCCESS
            self.stdout.write(
                style(
                    f"  {r.label}: scanned={r.scanned} clean={c[CLEAN]} legacy={c[LEGACY]} "
                    f"plaintext={c[PLAINTEXT]} unreadable={c[UNREADABLE]} empty={c[EMPTY]}"
                )
            )
            for bucket in (LEGACY, PLAINTEXT, UNREADABLE):
                if r.samples.get(bucket):
                    self.stdout.write(f"      {bucket} pks (sample): {', '.join(r.samples[bucket])}")

        self.stdout.write("")
        if total_legacy:
            self.stdout.write(
                self.style.ERROR(
                    f"{total_legacy} row(s) still depend on a SECRET_KEY-derived key. Re-encrypt them before "
                    "dropping the old key from SECRET_KEY / SECRET_KEY_FALLBACKS."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "No rows depend on a SECRET_KEY-derived key — safe to drop the old key once it is no longer "
                    "needed in SECRET_KEY_FALLBACKS for Django session/CSRF rotation."
                )
            )
        if total_plaintext or total_unreadable:
            self.stdout.write(
                self.style.WARNING(
                    f"{total_plaintext} plaintext and {total_unreadable} unreadable row(s) found — these do not "
                    "block rotation but should be inspected separately."
                )
            )
