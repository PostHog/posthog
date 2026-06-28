from posthog.test.base import BaseTest

from posthog.models.share_password import SharePassword
from posthog.models.sharing_configuration import SharingConfiguration

from products.dashboards.backend.models.dashboard import Dashboard


class TestSharingConfigurationModel(BaseTest):
    """Test the SharingConfiguration Django model"""

    def test_rotate_access_token_preserves_settings(self):
        """Test that rotating access token preserves the settings"""
        settings_data = {
            "whitelabel": True,
            "noHeader": False,
            "showInspector": True,
            "legend": False,
            "detailed": True,
            "customSetting": "preserved",
        }
        original_config = SharingConfiguration.objects.create(team=self.team, enabled=True, settings=settings_data)

        # Rotate token
        new_config = original_config.rotate_access_token()

        # Settings should be preserved
        assert new_config.settings == settings_data
        assert new_config.access_token != original_config.access_token
        assert new_config.enabled == original_config.enabled

    def test_rotate_access_token_preserves_password_protection(self):
        original_config = SharingConfiguration.objects.create(
            team=self.team,
            enabled=True,
            password_required=True,
        )
        pw, _ = SharePassword.create_password(
            sharing_configuration=original_config,
            created_by=self.user,
            raw_password="test-password",
            note="test note",
        )
        # Also create an inactive password that should NOT be cloned
        inactive_pw, _ = SharePassword.create_password(
            sharing_configuration=original_config,
            created_by=self.user,
            raw_password="inactive-password",
            note="inactive",
        )
        inactive_pw.is_active = False
        inactive_pw.save()

        new_config = original_config.rotate_access_token()

        assert new_config.password_required is True
        assert new_config.access_token != original_config.access_token

        # New config should have cloned active passwords
        new_passwords = list(new_config.share_passwords.all())
        assert len(new_passwords) == 1
        assert new_passwords[0].note == "test note"
        assert new_passwords[0].is_active is True
        assert new_passwords[0].check_password("test-password")

        # Old config passwords should be untouched
        assert original_config.share_passwords.count() == 2
        assert original_config.share_passwords.filter(is_active=True).count() == 1

    def test_rotate_access_token_non_password_protected_stays_unprotected(self):
        original_config = SharingConfiguration.objects.create(
            team=self.team,
            enabled=True,
            password_required=False,
        )

        new_config = original_config.rotate_access_token()

        assert new_config.password_required is False
        assert new_config.share_passwords.count() == 0

    def test_rotate_access_token_clones_all_active_passwords(self):
        original_config = SharingConfiguration.objects.create(
            team=self.team,
            enabled=True,
            password_required=True,
        )
        SharePassword.create_password(
            sharing_configuration=original_config,
            created_by=self.user,
            raw_password="password-one",
            note="first",
        )
        SharePassword.create_password(
            sharing_configuration=original_config,
            created_by=self.user,
            raw_password="password-two",
            note="second",
        )

        new_config = original_config.rotate_access_token()

        new_passwords = list(new_config.share_passwords.order_by("note"))
        assert len(new_passwords) == 2
        assert new_passwords[0].note == "first"
        assert new_passwords[0].check_password("password-one")
        assert new_passwords[1].note == "second"
        assert new_passwords[1].check_password("password-two")

    def test_rotate_access_token_expires_duplicate_active_configs(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="rotate duplicate dashboard", created_by=self.user)
        original_config = SharingConfiguration.objects.create(
            team=self.team,
            dashboard=dashboard,
            enabled=True,
            access_token="rotate_duplicate_one",
        )
        duplicate_config = SharingConfiguration.objects.create(
            team=self.team,
            dashboard=dashboard,
            enabled=True,
            access_token="rotate_duplicate_two",
        )

        new_config = original_config.rotate_access_token()

        original_config.refresh_from_db()
        duplicate_config.refresh_from_db()
        assert SharingConfiguration.objects.filter(dashboard=dashboard, expires_at__isnull=True).count() == 1
        assert new_config.expires_at is None
        assert original_config.expires_at is not None
        assert duplicate_config.expires_at is not None
        assert new_config.access_token not in {original_config.access_token, duplicate_config.access_token}
