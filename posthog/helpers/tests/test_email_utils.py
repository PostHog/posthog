from django.test import TestCase

from posthog.helpers.email_utils import EmailLookupHandler, EmailNormalizer, EmailValidationHelper
from posthog.models.user import User


class TestEmailNormalizer(TestCase):
    def test_normalize(self):
        """Test that email normalization works correctly."""
        test_cases = [
            ("test@EXAMPLE.COM", "test@example.com"),
            ("TEST@example.com", "test@example.com"),
            ("Test@Example.Com", "test@example.com"),
            ("USER@GMAIL.COM", "user@gmail.com"),
            ("user@gmail.com", "user@gmail.com"),
            ("User.Name+Tag@Example.ORG", "user.name+tag@example.org"),
            ("", ""),
        ]

        for input_email, expected in test_cases:
            with self.subTest(input_email=input_email):
                result = EmailNormalizer.normalize(input_email)
                self.assertEqual(result, expected)


class TestEmailLookupHandler(TestCase):
    def test_get_user_by_email_no_user(self):
        """Test getting user by email when none exists."""
        result = EmailLookupHandler.get_user_by_email("nonexistent@example.com")
        self.assertIsNone(result)

    def test_get_user_by_email_case_insensitive(self):
        """Test getting user by email with case variations."""
        user = User(email="Test@Example.COM", first_name="Test", last_name="User")
        user.set_password("testpass123")
        user.save()

        try:
            test_variations = ["test@example.com", "Test@Example.COM", "TEST@EXAMPLE.COM", "test@EXAMPLE.com"]

            for email_variation in test_variations:
                with self.subTest(email=email_variation):
                    found_user = EmailLookupHandler.get_user_by_email(email_variation)
                    self.assertIsNotNone(found_user)
                    if found_user is not None:
                        self.assertEqual(found_user.id, user.id)
        finally:
            user.delete()


class TestEmailValidationHelper(TestCase):
    def test_user_exists_no_user(self):
        """Test checking if user exists when none exists."""
        result = EmailValidationHelper.user_exists("nonexistent@example.com")
        self.assertFalse(result)

    def test_user_exists_with_user(self):
        """Test checking if user exists when user exists."""
        user = User.objects.create_user(email="TestExists@Example.COM", password="testpass123", first_name="Test")

        try:
            test_variations = [
                "testexists@example.com",
                "TestExists@Example.COM",
                "TESTEXISTS@EXAMPLE.COM",
                "testexists@EXAMPLE.com",
            ]

            for email_variation in test_variations:
                with self.subTest(email=email_variation):
                    result = EmailValidationHelper.user_exists(email_variation)
                    self.assertTrue(result)
        finally:
            user.delete()
