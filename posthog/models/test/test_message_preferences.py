from posthog.models.message_preferences import MessageRecipientPreference
from posthog.models.message_category import MessageCategory
from posthog.models.message_preferences import PreferenceStatus

from posthog.test.base import BaseTest
from django.test import Client
from django.db import IntegrityError
import uuid


class TestMessagePreferences(BaseTest):
    def setUp(self):
        super().setUp()
        team = self.organization.teams.first()
        if not team:
            raise ValueError("Test requires a team")
        self.team = team
        self.category = MessageCategory.objects.create(
            team=self.team, key="newsletter", name="Newsletter Updates", description="Weekly product updates"
        )
        self.category2 = MessageCategory.objects.create(
            team=self.team, key="product_updates", name="Product Updates", description="Product release notes"
        )
        self.recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )
        self.client = Client()
        self.token = self.recipient.generate_preferences_token()

    def test_create_message_category(self):
        category = MessageCategory.objects.create(
            team=self.team, key="marketing", name="Marketing", description="Marketing updates"
        )
        self.assertEqual(category.key, "marketing")
        self.assertEqual(str(category), "Marketing")

    def test_create_recipient_preference(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test2@example.com", preferences={}
        )
        self.assertEqual(recipient.identifier, "test2@example.com")
        self.assertEqual(recipient.preferences, {})
        self.assertEqual(str(recipient), "Preferences for test2@example.com")

    def test_duplicate_recipient_preference(self):
        MessageRecipientPreference.objects.create(team=self.team, identifier="test3@example.com", preferences={})
        with self.assertRaises(IntegrityError):  # Django will raise IntegrityError
            MessageRecipientPreference.objects.create(team=self.team, identifier="test3@example.com", preferences={})

    def test_set_preference(self):
        # Test setting a new preference
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test4@example.com", preferences={}
        )

        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_IN)
        self.assertEqual(recipient.get_preference(self.category.id), PreferenceStatus.OPTED_IN)

        # Test updating existing preference
        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_OUT)
        self.assertEqual(recipient.get_preference(self.category.id), PreferenceStatus.OPTED_OUT)

    def test_get_preference(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test5@example.com", preferences={}
        )

        # Test non-existent preference
        self.assertEqual(recipient.get_preference(uuid.uuid4()), PreferenceStatus.NO_PREFERENCE)

        # Test existing preference
        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_IN)
        self.assertEqual(recipient.get_preference(self.category.id), PreferenceStatus.OPTED_IN)

    def test_get_all_preferences(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test6@example.com", preferences={}
        )

        # Set multiple preferences
        category2 = MessageCategory.objects.create(
            team=self.team, key="product_updates_2", name="Product Updates 2", description="Product release notes 2"
        )

        recipient.set_preference(self.category.id, PreferenceStatus.OPTED_IN)
        recipient.set_preference(category2.id, PreferenceStatus.OPTED_OUT)

        # Test get_preferences method (returns dict of UUID to PreferenceStatus)
        preferences = recipient.get_preferences()
        self.assertEqual(preferences[self.category.id], PreferenceStatus.OPTED_IN)
        self.assertEqual(preferences[category2.id], PreferenceStatus.OPTED_OUT)

        # Test get_all_preference method (also returns dict of UUID to PreferenceStatus)
        all_preferences = recipient.get_all_preference()
        self.assertEqual(all_preferences[self.category.id], PreferenceStatus.OPTED_IN)
        self.assertEqual(all_preferences[category2.id], PreferenceStatus.OPTED_OUT)

    def test_get_or_create_for_identifier(self):
        # Test creating a new recipient
        defaults = {self.category.id: PreferenceStatus.OPTED_IN}
        recipient = MessageRecipientPreference.get_or_create_for_identifier(
            team_id=self.team.id, identifier="new@example.com", defaults=defaults
        )

        self.assertEqual(recipient.identifier, "new@example.com")
        self.assertEqual(recipient.team_id, self.team.id)
        # Check that the preference was set correctly
        self.assertEqual(recipient.get_preference(self.category.id), PreferenceStatus.OPTED_IN)

        # Test getting an existing recipient
        existing_recipient = MessageRecipientPreference.get_or_create_for_identifier(
            team_id=self.team.id, identifier="new@example.com"
        )

        # Should be the same instance
        self.assertEqual(existing_recipient.id, recipient.id)
        self.assertEqual(existing_recipient.get_preference(self.category.id), PreferenceStatus.OPTED_IN)

    def test_set_preference_validation(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test_validation@example.com", preferences={}
        )

        # Test that only PreferenceStatus enum values are accepted
        with self.assertRaises(ValueError):
            recipient.set_preference(self.category.id, "INVALID_STATUS")

    def test_token_generation_and_validation(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test7@example.com", preferences={}
        )

        # Test token generation
        token = recipient.generate_preferences_token()
        self.assertIsNotNone(token)

        # Test token validation
        validated_recipient, error = MessageRecipientPreference.validate_preferences_token(token)
        self.assertIsNotNone(validated_recipient, "Validated recipient should not be None")
        self.assertEqual(error, "")
        # Only check ID if we have a recipient
        if validated_recipient:  # This satisfies the type checker
            self.assertEqual(validated_recipient.id, recipient.id)

        # Test invalid token
        invalid_recipient, error = MessageRecipientPreference.validate_preferences_token("invalid-token")
        self.assertIsNone(invalid_recipient)
        self.assertNotEqual(error, "")
