import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError
from django.test import Client

import posthog.plugins.plugin_server_api as plugin_server_api
from posthog.models.message_category import MessageCategory
from posthog.models.message_preferences import MessageRecipientPreference, PreferenceStatus


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
        self._token_patch = patch.object(
            plugin_server_api, "generate_messaging_preferences_token", return_value="dummy-token"
        )
        self._token_patch.start()
        self.token = plugin_server_api.generate_messaging_preferences_token(self.team.id, self.recipient.identifier)

    def tearDown(self):
        self._token_patch.stop()
        super().tearDown()

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
        self.assertEqual(recipient.get_preference(str(uuid.uuid4())), PreferenceStatus.NO_PREFERENCE)

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

        # Test get_all_preferences method (returns dict of UUID to PreferenceStatus)
        preferences = recipient.get_all_preferences()
        self.assertEqual(preferences[str(self.category.id)], PreferenceStatus.OPTED_IN)
        self.assertEqual(preferences[str(category2.id)], PreferenceStatus.OPTED_OUT)

        # Test get_all_preference method (also returns dict of UUID to PreferenceStatus)
        all_preferences = recipient.get_all_preferences()
        self.assertEqual(all_preferences[str(self.category.id)], PreferenceStatus.OPTED_IN)
        self.assertEqual(all_preferences[str(category2.id)], PreferenceStatus.OPTED_OUT)

    def test_set_preference_validation(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test_validation@example.com", preferences={}
        )

        # Test that only PreferenceStatus enum values are accepted
        with self.assertRaises(ValueError):
            recipient.set_preference(self.category.id, "INVALID_STATUS")  # type: ignore[arg-type]
