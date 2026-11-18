from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework import serializers, status

from posthog.models.team.team import Team

from products.conversations.backend.ai.ticket_context import MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS
from products.conversations.backend.api.ai_context import validate_ai_context_conversations_settings
from products.customer_analytics.backend.facade.testing import create_custom_property_definition


class TestValidateAiContextConversationsSettings(SimpleTestCase):
    def test_null_becomes_empty_list(self) -> None:
        value = validate_ai_context_conversations_settings({"ai_context_account_property_ids": None}, team_id=1)
        assert value["ai_context_account_property_ids"] == []

    def test_rejects_non_list_and_non_uuid(self) -> None:
        with self.assertRaises(serializers.ValidationError):
            validate_ai_context_conversations_settings({"ai_context_account_property_ids": "nope"}, team_id=1)
        with self.assertRaises(serializers.ValidationError):
            validate_ai_context_conversations_settings({"ai_context_account_property_ids": ["not-a-uuid"]}, team_id=1)

    def test_keeps_account_defs_in_order_and_caps(self) -> None:
        ids = [uuid4() for _ in range(MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS + 2)]
        with patch(
            "products.conversations.backend.api.ai_context.get_custom_property_definition_target_type",
            return_value="account",
        ) as mocked:
            value = validate_ai_context_conversations_settings(
                {"ai_context_account_property_ids": [str(item) for item in ids]}, team_id=9
            )
        assert mocked.call_count == MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS
        assert [call.args[1] for call in mocked.call_args_list] == [
            str(item) for item in ids[:MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS]
        ]
        assert value["ai_context_account_property_ids"] == [
            str(item) for item in ids[:MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS]
        ]

    def test_creation_drops_every_id(self) -> None:
        # No team exists yet on create, so nothing can own a definition.
        value = validate_ai_context_conversations_settings(
            {"ai_context_account_property_ids": [str(uuid4())]}, team_id=None
        )
        assert value["ai_context_account_property_ids"] == []

    def test_creation_still_rejects_malformed_ids(self) -> None:
        # Dropping every id on create must not short-circuit the shape checks.
        with self.assertRaises(serializers.ValidationError):
            validate_ai_context_conversations_settings({"ai_context_account_property_ids": ["nope"]}, team_id=None)

    def test_drops_missing_and_non_account_defs(self) -> None:
        keep = uuid4()
        skip = uuid4()

        def target_type(_team_id: int, definition_id: str) -> str | None:
            if definition_id == str(keep):
                return "account"
            if definition_id == str(skip):
                return "person"
            return None

        with patch(
            "products.conversations.backend.api.ai_context.get_custom_property_definition_target_type",
            side_effect=target_type,
        ):
            value = validate_ai_context_conversations_settings(
                {"ai_context_account_property_ids": [str(keep), str(skip)]},
                team_id=1,
            )
        assert value["ai_context_account_property_ids"] == [str(keep)]


class TestAIContextAccountPropertiesAPI(APIBaseTest):
    def test_lists_account_properties_for_this_team_only(self) -> None:
        mine = create_custom_property_definition(team_id=self.team.id, name="Plan", target_type="account")
        create_custom_property_definition(team_id=self.team.id, name="Role", target_type="person")
        other_team = Team.objects.create(organization=self.organization, name="Other")
        create_custom_property_definition(team_id=other_team.id, name="Other plan", target_type="account")

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ai_context_account_properties/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [row["name"] for row in body] == ["Plan"]
        assert body[0]["id"] == str(mine.id)
