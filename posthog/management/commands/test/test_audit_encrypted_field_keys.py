import json
import base64
from io import StringIO
from typing import Any, cast

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections, router
from django.test import SimpleTestCase, override_settings

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from posthog.management.commands.audit_encrypted_field_keys import (
    CLEAN,
    EMPTY,
    LEGACY,
    PLAINTEXT,
    UNREADABLE,
    Command,
    _classify_leaf,
    _decryptable,
    _leaves,
    _legacy_fernet,
    _looks_like_fernet_token,
    _salt_only_fernet,
    classify,
)
from posthog.models.integration import Integration

# ENCRYPTION_KEY and OTHER_KEY are used directly as Fernet keys, so they must be exactly 32 bytes.
# SECRET and SALT_RAW only feed PBKDF2 (password / salt), so their length is irrelevant.
SALT_RAW = "a" * 32
SECRET = "b" * 32
ENCRYPTION_KEY = "c" * 32
OTHER_KEY = "d" * 32


def _salt_fernet(raw_key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(raw_key.encode("utf-8")))


def _secret_derived_fernet(secret_key: str, salt_key: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt_key.encode("utf-8"),
        iterations=100000,
        backend=default_backend(),
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(secret_key.encode("utf-8"))))


@override_settings(
    ENCRYPTION_SALT_KEYS=[ENCRYPTION_KEY], SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[], SALT_KEY=[SALT_RAW]
)
class TestAuditClassify(SimpleTestCase):
    def setUp(self):
        self.salt_only = _salt_only_fernet()
        self.legacy = _legacy_fernet()

    def _enc_salt(self, plaintext="secret"):
        return _salt_fernet(ENCRYPTION_KEY).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _enc_legacy(self, plaintext="secret"):
        return _secret_derived_fernet(SECRET, SALT_RAW).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _enc_other(self, plaintext="secret"):
        return _salt_fernet(OTHER_KEY).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def test_scalar_token_under_encryption_salt_key_is_clean(self):
        assert classify(self._enc_salt(), self.salt_only, self.legacy) == CLEAN

    def test_scalar_token_under_secret_derived_key_is_legacy(self):
        assert classify(self._enc_legacy(), self.salt_only, self.legacy) == LEGACY

    def test_token_under_unknown_key_is_unreadable(self):
        assert classify(self._enc_other(), self.salt_only, self.legacy) == UNREADABLE

    def test_non_token_string_is_plaintext(self):
        assert classify("not-encrypted-at-all", self.salt_only, self.legacy) == PLAINTEXT

    def test_empty_and_trivial_values_are_empty(self):
        values: list[object] = [None, "", "{}", "[]", "null", {}, []]
        for value in values:
            assert classify(value, self.salt_only, self.legacy) == EMPTY, value

    def test_json_field_all_leaves_clean(self):
        raw = {"a": self._enc_salt("x"), "nested": {"b": self._enc_salt("y")}, "list": [self._enc_salt("z")]}
        assert classify(raw, self.salt_only, self.legacy) == CLEAN

    def test_json_field_with_one_legacy_leaf_is_legacy(self):
        raw = {"a": self._enc_salt("x"), "b": self._enc_legacy("y")}
        assert classify(raw, self.salt_only, self.legacy) == LEGACY

    def test_json_field_with_one_plaintext_leaf_is_plaintext(self):
        # With no legacy/unreadable leaf, a never-encrypted leaf dominates clean ones — needs inspection
        raw = {"a": self._enc_salt("x"), "b": "leaked-plaintext"}
        assert classify(raw, self.salt_only, self.legacy) == PLAINTEXT

    def test_json_field_legacy_leaf_beats_plaintext_leaf(self):
        # Regression: a legacy token is stranded on rotation, so it must win over a plaintext sibling —
        # otherwise the row would be hidden from `legacy` and safe_to_drop_secret_key could read true
        raw = {"a": self._enc_legacy("x"), "b": "leaked-plaintext"}
        assert classify(raw, self.salt_only, self.legacy) == LEGACY

    def test_json_field_legacy_leaf_beats_unreadable_leaf(self):
        raw = {"a": self._enc_legacy("x"), "b": self._enc_other("y")}
        assert classify(raw, self.salt_only, self.legacy) == LEGACY

    def test_json_field_unreadable_leaf_beats_plaintext_leaf(self):
        raw = {"a": self._enc_other("x"), "b": "leaked-plaintext"}
        assert classify(raw, self.salt_only, self.legacy) == UNREADABLE

    @override_settings(SECRET_KEY="new-secret", SECRET_KEY_FALLBACKS=[SECRET], SALT_KEY=[SALT_RAW])
    def test_secret_derived_leaf_still_legacy_via_fallback(self):
        legacy = _legacy_fernet()
        assert classify(self._enc_legacy(), self.salt_only, legacy) == LEGACY


@override_settings(
    ENCRYPTION_SALT_KEYS=[ENCRYPTION_KEY], SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[], SALT_KEY=[SALT_RAW]
)
class TestAuditFieldArgument(SimpleTestCase):
    # --field resolves against the app registry before any DB access, so these need no database

    def test_unknown_field_raises_clear_error_listing_available_fields(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("audit_encrypted_field_keys", field="nope.Nope.nope")
        message = str(ctx.exception)
        assert "nope.Nope.nope" in message
        assert "did not match" in message
        # lists real fields so the user can fix the typo instead of concluding there are none
        assert "posthog.Integration.sensitive_config" in message


class TestAuditFernetBuilders(SimpleTestCase):
    @override_settings(ENCRYPTION_SALT_KEYS=[], SALT_KEY=[])
    def test_salt_only_fernet_is_none_when_no_keys(self):
        assert _salt_only_fernet() is None

    @override_settings(SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[], SALT_KEY=[])
    def test_legacy_fernet_is_none_when_no_salt_keys(self):
        assert _legacy_fernet() is None

    @override_settings(SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=["fb1", "fb2"], SALT_KEY=[SALT_RAW, "salt2"])
    def test_legacy_fernet_covers_secret_key_and_all_fallbacks(self):
        legacy = _legacy_fernet()
        assert isinstance(legacy, MultiFernet)
        # 3 secret keys (secret + 2 fallbacks) x 2 salt keys = 6 derived keys; each decrypts its own ciphertext
        token = _secret_derived_fernet("fb2", "salt2").encrypt(b"x").decode("utf-8")
        assert legacy.decrypt(token.encode("utf-8")) == b"x"


@override_settings(
    ENCRYPTION_SALT_KEYS=[ENCRYPTION_KEY], SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[], SALT_KEY=[SALT_RAW]
)
class TestAuditLeafHelpers(SimpleTestCase):
    # The leaf-walking and token-probing helpers underneath classify(), tested in isolation.

    def setUp(self):
        self.salt_only = _salt_only_fernet()
        self.legacy = _legacy_fernet()
        self.clean_token = _salt_fernet(ENCRYPTION_KEY).encrypt(b"secret").decode("utf-8")
        self.legacy_token = _secret_derived_fernet(SECRET, SALT_RAW).encrypt(b"secret").decode("utf-8")
        self.other_token = _salt_fernet(OTHER_KEY).encrypt(b"secret").decode("utf-8")

    def test_leaves_flattens_every_nesting_into_only_strings(self):
        cases: list[tuple[object, list[str]]] = [
            ("token", ["token"]),  # scalar field stores a single token
            ({"a": "t1", "b": "t2"}, ["t1", "t2"]),  # jsonb object — one token per value
            (["t1", "t2"], ["t1", "t2"]),
            ({"a": {"b": "t"}, "c": ["d", "e"]}, ["t", "d", "e"]),  # arbitrarily nested
            ({"a": "t", "b": 5, "c": None}, ["t"]),  # non-string leaves carry no token, so dropped
            (123, []),
            (None, []),
            ({}, []),
            ([], []),
        ]
        for value, expected in cases:
            assert _leaves(value) == expected, value

    def test_looks_like_fernet_token_only_for_real_tokens(self):
        too_short = base64.urlsafe_b64encode(b"short").decode("utf-8")
        wrong_version_byte = base64.urlsafe_b64encode(b"\x00" + b"x" * 80).decode("utf-8")
        cases: list[tuple[str, bool]] = [
            (self.clean_token, True),
            (self.legacy_token, True),
            (self.other_token, True),  # token-shaped even when no configured key decrypts it
            ("not-base64-at-all!!", False),  # invalid base64 padding
            ("plaintext", False),
            (too_short, False),  # decodes to < 73 bytes
            (wrong_version_byte, False),  # long enough, but first byte is not Fernet's 0x80
        ]
        for value, expected in cases:
            assert _looks_like_fernet_token(value) is expected, value

    def test_decryptable_is_false_without_a_fernet(self):
        assert _decryptable(None, self.clean_token) is False

    def test_decryptable_matches_only_the_right_key(self):
        assert _decryptable(self.salt_only, self.clean_token) is True
        assert _decryptable(self.salt_only, self.legacy_token) is False
        assert _decryptable(self.legacy, self.legacy_token) is True
        assert _decryptable(self.salt_only, "not-even-a-token") is False

    def test_classify_leaf_maps_each_token_to_its_bucket(self):
        cases: list[tuple[str, str]] = [
            (self.clean_token, CLEAN),
            (self.legacy_token, LEGACY),
            (self.other_token, UNREADABLE),
            ("leaked-plaintext", PLAINTEXT),
        ]
        for leaf, expected in cases:
            assert _classify_leaf(leaf, self.salt_only, self.legacy) == expected, leaf


class TestAuditCoerceRaw(SimpleTestCase):
    # A raw cursor returns jsonb as a JSON string under Django's psycopg config; _coerce_raw decodes it
    # so per-leaf tokens are walked individually instead of the whole document reading as one opaque leaf.

    def test_jsonb_string_is_parsed_only_for_json_columns(self):
        # is_json_column=True → parse so siblings become distinct leaves
        assert Command._coerce_raw('{"a": "tok1", "b": "tok2"}', True) == {"a": "tok1", "b": "tok2"}
        # is_json_column=False → a text column already holds the single token, leave it untouched
        assert Command._coerce_raw("a-single-token", False) == "a-single-token"

    def test_passthrough_for_non_string_and_unparseable_values(self):
        assert Command._coerce_raw(None, True) is None  # NULL jsonb
        assert Command._coerce_raw({"a": "tok"}, True) == {"a": "tok"}  # already-parsed dict survives
        assert Command._coerce_raw("not-json", True) == "not-json"  # invalid JSON falls through unchanged


@override_settings(
    ENCRYPTION_SALT_KEYS=[ENCRYPTION_KEY], SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[], SALT_KEY=[SALT_RAW]
)
class TestAuditCommandEndToEnd(BaseTest):
    # Drives the whole Command against real Integration.sensitive_config rows. Ciphertext is injected
    # via raw SQL so each row lands in a known classification — the ORM would re-encrypt under the
    # current salt key, collapsing exactly the legacy-vs-clean distinction the audit measures.

    FIELD = "posthog.Integration.sensitive_config"

    def setUp(self):
        super().setUp()
        self._next_suffix = 0

    def _make_integration(self, raw_value: object) -> int:
        self._next_suffix += 1
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id=f"audit-test-{self._next_suffix}", errors=""
        )
        connection = connections[router.db_for_write(Integration)]
        quote = connection.ops.quote_name
        table = quote(Integration._meta.db_table)
        # cast to Any: sensitive_config is wrapped in field_access_control, so the django-stubs
        # plugin doesn't see it as a model field and rejects the get_field string literal.
        column = quote(cast(Any, Integration)._meta.get_field("sensitive_config").column)
        pk_column = quote(Integration._meta.pk.column)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {column} = %s::jsonb WHERE {pk_column} = %s",
                [json.dumps(raw_value), integration.pk],
            )
        return integration.pk

    def _clean(self, plaintext="secret"):
        return _salt_fernet(ENCRYPTION_KEY).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _legacy(self, plaintext="secret"):
        return _secret_derived_fernet(SECRET, SALT_RAW).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _other(self, plaintext="secret"):
        return _salt_fernet(OTHER_KEY).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _run_json(self, **options) -> dict:
        out = StringIO()
        call_command("audit_encrypted_field_keys", field=self.FIELD, json=True, stdout=out, **options)
        payload = json.loads(out.getvalue())
        assert len(payload["fields"]) == 1, "--field should restrict the run to a single field"
        return payload

    def test_mixed_rows_are_counted_and_legacy_blocks_rotation(self):
        legacy_pk = self._make_integration({"k": self._legacy()})
        self._make_integration({"k": self._clean()})
        self._make_integration({"k": self._other()})
        self._make_integration({"k": "leaked-plaintext"})
        self._make_integration({})  # empty jsonb — no leaf to classify

        payload = self._run_json()
        report = payload["fields"][0]

        assert report["scanned"] == 5
        assert report["counts"] == {CLEAN: 1, LEGACY: 1, PLAINTEXT: 1, UNREADABLE: 1, EMPTY: 1}
        assert payload["safe_to_drop_secret_key"] is False
        assert str(legacy_pk) in report["samples"][LEGACY]
        assert report["error"] is None

    def test_json_field_is_walked_per_leaf_through_the_db(self):
        # Regression: a jsonb column comes back from the cursor as a JSON string. Without parsing it, the
        # whole document reads as one non-token leaf (plaintext) and a legacy leaf inside would be missed,
        # letting safe_to_drop_secret_key report true while stranded JSON tokens still exist.
        self._make_integration({"a": self._clean(), "b": self._legacy(), "nested": {"c": self._clean()}})
        self._make_integration({"a": self._clean(), "nested": {"c": self._clean()}})

        payload = self._run_json()
        report = payload["fields"][0]

        assert report["counts"] == {CLEAN: 1, LEGACY: 1, PLAINTEXT: 0, UNREADABLE: 0, EMPTY: 0}
        assert payload["safe_to_drop_secret_key"] is False

    def test_clean_and_empty_only_is_safe_to_drop(self):
        self._make_integration({"k": self._clean()})
        self._make_integration({})

        payload = self._run_json()

        assert payload["safe_to_drop_secret_key"] is True
        assert payload["fields"][0]["counts"][LEGACY] == 0

    def test_plaintext_and_unreadable_do_not_block_rotation(self):
        # Only LEGACY strands rows on rotation; plaintext / unreadable are flagged but still safe to drop
        self._make_integration({"k": self._clean()})
        self._make_integration({"k": "leaked-plaintext"})
        self._make_integration({"k": self._other()})

        payload = self._run_json()
        report = payload["fields"][0]

        assert payload["safe_to_drop_secret_key"] is True
        assert report["counts"][PLAINTEXT] == 1
        assert report["counts"][UNREADABLE] == 1

    def test_limit_caps_rows_scanned(self):
        for _ in range(4):
            self._make_integration({"k": self._clean()})

        report = self._run_json(limit=2)["fields"][0]

        assert report["scanned"] == 2

    def test_small_batch_size_paginates_across_every_row(self):
        for _ in range(3):
            self._make_integration({"k": self._clean()})

        # batch_size=1 forces the keyset-pagination WHERE pk > %s branch on every row
        report = self._run_json(batch_size=1)["fields"][0]

        assert report["scanned"] == 3
        assert report["counts"][CLEAN] == 3

    def test_samples_option_caps_recorded_pks(self):
        for _ in range(3):
            self._make_integration({"k": self._legacy()})

        report = self._run_json(samples=2)["fields"][0]

        assert report["counts"][LEGACY] == 3
        assert len(report["samples"][LEGACY]) == 2

    def test_console_output_summarizes_and_warns_on_legacy(self):
        self._make_integration({"k": self._legacy()})
        self._make_integration({"k": self._clean()})

        out = StringIO()
        call_command("audit_encrypted_field_keys", field=self.FIELD, stdout=out, no_color=True)
        text = out.getvalue()

        assert self.FIELD in text
        assert "legacy=1" in text
        assert "clean=1" in text
        assert "still depend on a SECRET_KEY-derived key" in text

    @override_settings(
        ENCRYPTION_SALT_KEYS=[ENCRYPTION_KEY],
        SECRET_KEY="rotated-secret",
        SECRET_KEY_FALLBACKS=[SECRET],
        SALT_KEY=[SALT_RAW],
    )
    def test_row_under_rotated_secret_key_stays_legacy_via_fallback(self):
        # The crux of the feature: after SECRET_KEY rotates (old key moved to fallbacks), a row encrypted
        # with the old key must still classify as LEGACY — not UNREADABLE — so rotation isn't reported safe
        self._make_integration({"k": self._legacy()})

        report = self._run_json()["fields"][0]

        assert report["counts"][LEGACY] == 1
        assert report["counts"][UNREADABLE] == 0


class TestAuditCommandErrors(SimpleTestCase):
    @override_settings(ENCRYPTION_SALT_KEYS=[], SALT_KEY=[SALT_RAW])
    def test_empty_encryption_salt_keys_raises_before_any_db_access(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("audit_encrypted_field_keys")
        assert "ENCRYPTION_SALT_KEYS is empty" in str(ctx.exception)
