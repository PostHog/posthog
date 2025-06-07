from posthog.models.message_preferences import MessageCategory, MessageRecipientPreference, PreferenceStatus
from posthog.test.base import BaseTest
import uuid


class TestMessagePreferences(BaseTest):
    def setUp(self):
        super().setUp()
        self.team = self.organization.teams.first()
        self.category = MessageCategory.objects.create(
            team=self.team, key="newsletter", name="Newsletter Updates", description="Weekly product updates"
        )

    def test_create_message_category(self):
        category = MessageCategory.objects.create(
            team=self.team, key="marketing", name="Marketing", description="Marketing updates"
        )
        self.assertEqual(category.key, "marketing")
        self.assertEqual(str(category), "Marketing")

    def test_create_recipient_preference(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )
        self.assertEqual(recipient.identifier, "test@example.com")
        self.assertEqual(recipient.preferences, {})
        self.assertEqual(str(recipient), "Preferences for test@example.com")

    def test_duplicate_recipient_preference(self):
        MessageRecipientPreference.objects.create(team=self.team, identifier="test@example.com", preferences={})
        with self.assertRaises(Exception):  # Django will raise IntegrityError
            MessageRecipientPreference.objects.create(team=self.team, identifier="test@example.com", preferences={})

    def test_set_preference(self):
        # Test setting a new preference
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )

        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_IN)
        self.assertEqual(recipient.get_preference(self.category.id), PreferenceStatus.OPTED_IN)

        # Test updating existing preference
        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_OUT)
        self.assertEqual(recipient.get_preference(self.category.id), PreferenceStatus.OPTED_OUT)

    def test_get_preference(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )

        # Test non-existent preference
        self.assertEqual(recipient.get_preference(uuid.uuid4()), PreferenceStatus.NO_PREFERENCE)

        # Test existing preference
        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_IN)
        self.assertEqual(recipient.get_preference(self.category.id), PreferenceStatus.OPTED_IN)

    def test_get_all_preferences(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )

        # Set multiple preferences
        category2 = MessageCategory.objects.create(
            team=self.team, key="product_updates", name="Product Updates", description="Product release notes"
        )

        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_IN)
        recipient.set_preference(category2.id, PreferenceStatus.OPTED_OUT)

        preferences = recipient.get_all_preferences()
        self.assertEqual(preferences[self.category.id], PreferenceStatus.OPTED_IN)
        self.assertEqual(preferences[category2.id], PreferenceStatus.OPTED_OUT)

    def test_token_generation_and_validation(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )

        # Test token generation
        token = recipient.generate_preferences_token()
        self.assertIsNotNone(token)

        # Test token validation
        validated_recipient, error = MessageRecipientPreference.validate_preferences_token(token)
        self.assertEqual(validated_recipient.id, recipient.id)
        self.assertEqual(error, "")
