from django.core.exceptions import ValidationError
from posthog.models.message_preferences import MessageCategory, RecipientIdentifier, MessagePreference
from posthog.test.base import BaseTest


class TestMessagePreferences(BaseTest):
    def setUp(self):
        super().setUp()
        self.category = MessageCategory.objects.create(
            key="newsletter", name="Newsletter Updates", description="Weekly product updates"
        )

    def test_create_message_category(self):
        category = MessageCategory.objects.create(key="marketing", name="Marketing", is_system_category=True)
        self.assertEqual(category.key, "marketing")
        self.assertTrue(category.is_system_category)
        self.assertEqual(str(category), "Marketing")

    def test_create_recipient_identifier_email(self):
        recipient = RecipientIdentifier.objects.create(identifier="test@example.com", type="email")
        self.assertEqual(recipient.identifier, "test@example.com")
        self.assertEqual(recipient.type, "email")
        self.assertEqual(str(recipient), "test@example.com (email)")

    def test_invalid_email_validation(self):
        with self.assertRaises(ValidationError):
            recipient = RecipientIdentifier(identifier="not-an-email", type="email")
            recipient.clean()

    def test_duplicate_recipient_identifier(self):
        RecipientIdentifier.objects.create(identifier="test@example.com", type="email")
        with self.assertRaises(Exception):  # Django will raise IntegrityError
            RecipientIdentifier.objects.create(identifier="test@example.com", type="email")

    def test_set_preference(self):
        # Test setting a new preference
        pref = MessagePreference.set_preference(
            identifier="test@example.com",
            identifier_type="email",
            category_key="newsletter",
            opted_in=True,
            reason="Test opt-in",
        )
        self.assertTrue(pref.opted_in)
        self.assertEqual(pref.reason, "Test opt-in")

        # Test updating existing preference
        updated_pref = MessagePreference.set_preference(
            identifier="test@example.com",
            identifier_type="email",
            category_key="newsletter",
            opted_in=False,
            reason="Changed mind",
        )
        self.assertEqual(pref.id, updated_pref.id)  # Same preference object
        self.assertFalse(updated_pref.opted_in)
        self.assertEqual(updated_pref.reason, "Changed mind")

    def test_get_preference(self):
        # Test non-existent preference
        pref = MessagePreference.get_preference(
            identifier="nonexistent@example.com", identifier_type="email", category_key="newsletter"
        )
        self.assertIsNone(pref)

        # Test existing preference
        MessagePreference.set_preference(
            identifier="test@example.com", identifier_type="email", category_key="newsletter", opted_in=True
        )
        pref = MessagePreference.get_preference(
            identifier="test@example.com", identifier_type="email", category_key="newsletter"
        )
        self.assertIsNotNone(pref)
        self.assertTrue(pref.opted_in)

    def test_multiple_identifier_types(self):
        # Test that same identifier can be used with different types
        RecipientIdentifier.objects.create(identifier="12345", type="phone")
        RecipientIdentifier.objects.create(identifier="12345", type="device")
        self.assertEqual(RecipientIdentifier.objects.filter(identifier="12345").count(), 2)
