from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.checks import Tags
from django.db import DEFAULT_DB_ALIAS
from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.admin.console.registry import console
from posthog.checks import (
    check_admin_console_staff_groups,
    check_allowed_ip_blocks,
    check_cron_schedules,
    check_encryption_salt_keys,
    check_object_storage_public_endpoint,
    check_oidc_signing_key,
    check_product_db_routes,
    check_temporal_client_tls,
    check_trusted_proxies,
)
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


class TestSettingWarnings(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "oidc_key_set",
                {"OAUTH2_PROVIDER": {**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": "key"}},
                check_oidc_signing_key,
                [],
            ),
            (
                "oidc_key_missing",
                {"OAUTH2_PROVIDER": {**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": ""}},
                check_oidc_signing_key,
                ["posthog.oauth.W001"],
            ),
            ("ip_blocks_valid", {"ALLOWED_IP_BLOCKS": ["10.0.0.0/8", "192.168.1.5"]}, check_allowed_ip_blocks, []),
            (
                "ip_blocks_invalid",
                {"ALLOWED_IP_BLOCKS": ["10.0.0.0/8", "10.0.0/8"]},
                check_allowed_ip_blocks,
                ["posthog.access.W001"],
            ),
            (
                "trusted_proxies_valid",
                {"TRUSTED_PROXIES": "10.0.0.1, 2001:db8::1,", "TRUST_ALL_PROXIES": False},
                check_trusted_proxies,
                [],
            ),
            (
                "trusted_proxies_cidr",
                {"TRUSTED_PROXIES": "10.0.0.1,10.0.0.0/8", "TRUST_ALL_PROXIES": False},
                check_trusted_proxies,
                ["posthog.access.W002"],
            ),
            (
                "cron_valid",
                {"CALCULATE_COHORTS_DAY_SCHEDULE": "*/2 6-17 * * *", "MATERIALIZE_COLUMNS_SCHEDULE_CRON": ""},
                check_cron_schedules,
                [],
            ),
            (
                "cron_unparseable",
                {"CALCULATE_COHORTS_DAY_SCHEDULE": "*/2 6-17 * *", "MATERIALIZE_COLUMNS_SCHEDULE_CRON": "0 25 * * *"},
                check_cron_schedules,
                ["posthog.schedules.W001", "posthog.schedules.W001"],
            ),
            (
                "temporal_tls_pair_complete",
                {"TEMPORAL_CLIENT_CERT": "cert", "TEMPORAL_CLIENT_KEY": "key"},
                check_temporal_client_tls,
                [],
            ),
            (
                "temporal_tls_key_missing",
                {"TEMPORAL_CLIENT_CERT": "cert", "TEMPORAL_CLIENT_KEY": None},
                check_temporal_client_tls,
                ["posthog.temporal.W001"],
            ),
        ]
    )
    def test_warns_only_on_a_bad_value(self, _name, overrides, check, expected_ids) -> None:
        with override_settings(**overrides):
            assert [message.id for message in check(None)] == expected_ids


class TestAdminConsoleStaffGroupsCheck(TestCase):
    @parameterized.expand([("every_group_exists", 0), ("a_group_is_missing", 1)])
    def test_warns_about_a_staff_group_that_does_not_exist(self, _name: str, missing_count: int) -> None:
        staff_groups = sorted(console.staff_groups())
        assert staff_groups, "No console owner has a staff group, so this test checks nothing."
        missing = staff_groups[:missing_count]
        for name in staff_groups:
            Group.objects.get_or_create(name=name)
        Group.objects.filter(name__in=missing).delete()

        warnings = check_admin_console_staff_groups(None, databases=[DEFAULT_DB_ALIAS])

        assert [(warning.id, missing[0] in warning.msg) for warning in warnings] == [
            ("posthog.admin_console.W001", True)
        ] * missing_count
        # Without the tag, Django would run the query on every startup.
        assert Tags.database in check_admin_console_staff_groups.tags  # type: ignore[attr-defined]
