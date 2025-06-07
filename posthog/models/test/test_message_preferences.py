from posthog.models.message_preferences import MessageCategory, MessageRecipientPreference
from posthog.test.base import BaseTest
from django.test import Client
from django.urls import reverse
import uuid
import json
from posthog.models.message_preferences import PreferenceStatus


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
        self.assertIsNotNone(validated_recipient, "Validated recipient should not be None")
        self.assertEqual(error, "")
        # Only check ID if we have a recipient
        if validated_recipient:  # This satisfies the type checker
            self.assertEqual(validated_recipient.id, recipient.id)

        # Test invalid token
        invalid_recipient, error = MessageRecipientPreference.validate_preferences_token("invalid-token")
        self.assertIsNone(invalid_recipient)
        self.assertNotEqual(error, "")

    def test_preferences_page_valid_token(self):
        response = self.client.get(reverse("preferences_page", kwargs={"token": self.token}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "message_preferences/preferences.html")

        # Check context
        self.assertEqual(response.context["recipient"], self.recipient)
        self.assertEqual(len(response.context["categories"]), 2)
        self.assertEqual(response.context["token"], self.token)

        # Verify categories are ordered by name
        categories = response.context["categories"]
        self.assertEqual(categories[0]["name"], "Newsletter Updates")
        self.assertEqual(categories[1]["name"], "Product Updates")

    def test_preferences_page_invalid_token(self):
        response = self.client.get(reverse("preferences_page", kwargs={"token": "invalid-token"}))
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "message_preferences/error.html")

    def test_preferences_page_expired_token(self):
        # This would require mocking time to properly test token expiration
        pass

    def test_update_preferences_valid(self):
        data = {"token": self.token, "preferences[]": [f"{self.category.id}:true", f"{self.category2.id}:false"]}
        response = self.client.post(reverse("update_preferences"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"success": True})

        # Verify preferences were updated
        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[self.category.id], PreferenceStatus.OPTED_IN)
        self.assertEqual(prefs[self.category2.id], PreferenceStatus.OPTED_OUT)

    def test_update_preferences_missing_token(self):
        response = self.client.post(
            reverse("update_preferences"),
            {"preferences[]": [f"{self.category.id}:true"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"error": "Missing token"})

    def test_update_preferences_invalid_token(self):
        data = {"token": "invalid-token", "preferences[]": [f"{self.category.id}:true"]}
        response = self.client.post(reverse("update_preferences"), data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", json.loads(response.content))

    def test_update_preferences_invalid_preference_format(self):
        data = {"token": self.token, "preferences[]": ["invalid:format"]}
        response = self.client.post(reverse("update_preferences"), data)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.content), {"error": "Failed to update preferences"})
