from django.contrib.auth.hashers import check_password
from django.test import TestCase

from posthog.models import Organization, SharePassword, SharingConfiguration, Team, User


class TestSharePassword(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.user = User.objects.create_user(email="test@example.com", password="testpass", first_name="Test")
        self.organization.memberships.create(user=self.user, level=15)
        self.team = Team.objects.create(name="Test Team", organization=self.organization)
        self.sharing_config = SharingConfiguration.objects.create(team=self.team, enabled=True, password_required=True)

    def test_create_password_with_custom_password(self):
        raw_password = "my-secure-password"
        share_password, returned_password = SharePassword.create_password(
            sharing_configuration=self.sharing_config,
            created_by=self.user,
            raw_password=raw_password,
            note="Test password",
        )

        self.assertEqual(returned_password, raw_password)
        self.assertEqual(share_password.note, "Test password")
        self.assertEqual(share_password.created_by, self.user)
        self.assertEqual(share_password.sharing_configuration, self.sharing_config)
        self.assertTrue(share_password.is_active)

        # Password should be hashed
        self.assertNotEqual(share_password.password_hash, raw_password)
        self.assertTrue(check_password(raw_password, share_password.password_hash))

    def test_create_password_with_generated_password(self):
        share_password, returned_password = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, note="Auto-generated password"
        )

        # Should generate a password
        self.assertIsNotNone(returned_password)
        self.assertTrue(len(returned_password) >= 16)  # Generated passwords should be secure
        self.assertEqual(share_password.note, "Auto-generated password")

        # Password should be hashed and verifiable
        self.assertTrue(share_password.check_password(returned_password))

    def test_check_password_success(self):
        raw_password = "test-password-123"
        share_password = SharePassword(sharing_configuration=self.sharing_config, created_by=self.user)
        share_password.set_password(raw_password)
        share_password.save()

        self.assertTrue(share_password.check_password(raw_password))

    def test_check_password_failure(self):
        raw_password = "test-password-123"
        share_password = SharePassword(sharing_configuration=self.sharing_config, created_by=self.user)
        share_password.set_password(raw_password)
        share_password.save()

        self.assertFalse(share_password.check_password("wrong-password"))

    def test_ordering(self):
        # Create multiple passwords with different timestamps
        password1 = SharePassword.objects.create(
            sharing_configuration=self.sharing_config, created_by=self.user, password_hash="hash1"
        )
        password2 = SharePassword.objects.create(
            sharing_configuration=self.sharing_config, created_by=self.user, password_hash="hash2"
        )

        # Should be ordered by -created_at (newest first)
        passwords = list(SharePassword.objects.all())
        self.assertEqual(passwords[0], password2)
        self.assertEqual(passwords[1], password1)

    def test_relationship_to_sharing_configuration(self):
        share_password = SharePassword.objects.create(
            sharing_configuration=self.sharing_config, created_by=self.user, password_hash="dummy-hash"
        )

        # Test reverse relationship
        self.assertIn(share_password, self.sharing_config.share_passwords.all())

    def test_cascade_delete_on_sharing_configuration(self):
        share_password = SharePassword.objects.create(
            sharing_configuration=self.sharing_config, created_by=self.user, password_hash="dummy-hash"
        )
        password_id = share_password.id

        # Delete sharing configuration should cascade delete password
        self.sharing_config.delete()

        self.assertFalse(SharePassword.objects.filter(id=password_id).exists())

    def test_set_null_on_user_delete(self):
        share_password = SharePassword.objects.create(
            sharing_configuration=self.sharing_config, created_by=self.user, password_hash="dummy-hash"
        )
        password_id = share_password.id

        # Delete user should set created_by to NULL but keep password
        self.user.delete()

        share_password.refresh_from_db()
        self.assertIsNone(share_password.created_by)
        self.assertTrue(SharePassword.objects.filter(id=password_id).exists())

    def test_str_representation_deleted_user(self):
        share_password = SharePassword.objects.create(
            sharing_configuration=self.sharing_config,
            created_by=self.user,
            password_hash="dummy-hash",
            note="Test note",
        )

        # Delete the user
        self.user.delete()
        share_password.refresh_from_db()

        # String representation should show "deleted user"
        str_repr = str(share_password)
        self.assertIn("deleted user", str_repr)
        self.assertIn("(Test note)", str_repr)
        self.assertIn(share_password.created_at.strftime("%Y-%m-%d"), str_repr)
