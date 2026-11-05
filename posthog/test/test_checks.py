from pathlib import Path

from django.test import SimpleTestCase, override_settings

from posthog.checks import check_encryption_salt_keys, check_object_storage_public_endpoint, check_product_db_routes
from posthog.product_db_router import get_product_db_routes
from posthog.settings.utils import get_list


class TestObjectStoragePublicEndpointCheck(SimpleTestCase):
    def test_no_error_for_valid_endpoint(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://public.example.com",
        ):
            assert check_object_storage_public_endpoint(None) == []

    def test_error_for_unsubstituted_placeholder(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://${POSTHOG_DOMAIN}",
        ):
            errors = check_object_storage_public_endpoint(None)

        assert len(errors) == 1
        assert errors[0].id == "posthog.storage.E001"

    def test_no_error_when_storage_disabled(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=False,
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://${POSTHOG_DOMAIN}",
        ):
            assert check_object_storage_public_endpoint(None) == []


class TestEncryptionSaltKeysCheck(SimpleTestCase):
    # System check that ENCRYPTION_SALT_KEYS entries are valid Fernet keys (exactly 32 bytes). Each is
    # used directly as a Fernet key, so a wrong-length one would otherwise crash opaquely on first use.

    @override_settings(ENCRYPTION_SALT_KEYS=["00beef0000beef0000beef0000beef00"])
    def test_single_valid_key_passes(self):
        assert check_encryption_salt_keys(None) == []

    @override_settings(ENCRYPTION_SALT_KEYS=get_list("00beef0000beef0000beef0000beef00," + "a" * 32))
    def test_two_valid_keys_pass(self):
        assert check_encryption_salt_keys(None) == []

    @override_settings(ENCRYPTION_SALT_KEYS=get_list(",".join(["a" * 32, "b" * 32, "c" * 32])))
    def test_three_valid_keys_pass(self):
        assert check_encryption_salt_keys(None) == []

    @override_settings(ENCRYPTION_SALT_KEYS=["tooshort"])
    def test_short_key_is_flagged(self):
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert errors[0].id == "posthog.encryption.E001"
        assert "ENCRYPTION_SALT_KEYS[0]" in errors[0].msg
        assert "got 8" in errors[0].msg

    @override_settings(ENCRYPTION_SALT_KEYS=["a" * 33])
    def test_long_key_is_flagged(self):
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert "got 33" in errors[0].msg

    @override_settings(ENCRYPTION_SALT_KEYS=["a" * 32, "b" * 31])
    def test_reports_index_of_offending_key(self):
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert "ENCRYPTION_SALT_KEYS[1]" in errors[0].msg

    @override_settings(ENCRYPTION_SALT_KEYS=["é" * 32])
    def test_counts_bytes_not_characters(self):
        # 32 'é' is 64 bytes in UTF-8 — must be flagged, since Fernet keys are byte-sized
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert "got 64" in errors[0].msg


class TestProductDBRouteChecks(SimpleTestCase):
    @override_settings(BASE_DIR=Path(__file__).resolve().parents[2])
    def test_check_passes_for_valid_route_config(self) -> None:
        get_product_db_routes.cache_clear()
        self.addCleanup(get_product_db_routes.cache_clear)

        self.assertEqual(check_product_db_routes(None), [])
