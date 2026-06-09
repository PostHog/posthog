import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from mistralai_azure import AssistantMessage

from posthog.models.team.team import Team

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_template import MessageTemplate
from products.workflows.backend.max_tools import CreateMessageTemplateTool

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.insights_assistant import InsightsAssistant

GENERATED_TEMPLATE = {
    "name": "Welcome email",
    "description": "A friendly welcome",
    "content": {
        "templating": "liquid",
        "email": {
            "subject": "Welcome to PostHog!",
            "text": "Hi there",
            "html": "<p>Hi {{ person.properties.name }}</p>",
            "design": {"body": {"rows": [{"id": "r1"}]}, "schemaVersion": 17},
        },
    },
}


class TestMaxToolsAPI(APIBaseTest):
    @patch.object(InsightsAssistant, "invoke")
    def test_create_and_query_insight_returns_json(self, mock_generate):
        mock_generate.return_value = [("message", AssistantMessage(content="Creating your insight", role="assistant"))]

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me daily active users", "insight_type": "trends"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "message")

        mock_generate.assert_called_once()

    def test_create_and_query_insight_missing_insight_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me data"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "insight_type")
        self.assertEqual(error["code"], "required")

    def test_create_and_query_insight_invalid_insight_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me data", "insight_type": "invalid_type"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "insight_type")

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_persists_and_returns_template(self, mock_run):
        mock_run.return_value = ("```json\n{}\n```", json.dumps(GENERATED_TEMPLATE))

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email for new signups"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()
        self.assertEqual(data["name"], "Welcome email")
        self.assertEqual(data["type"], "email")
        self.assertEqual(data["content"]["templating"], "liquid")
        self.assertEqual(data["content"]["email"]["subject"], "Welcome to PostHog!")

        template = MessageTemplate.objects.get(id=data["id"])
        self.assertEqual(template.team, self.team)
        self.assertEqual(template.created_by, self.user)
        self.assertEqual(template.content["email"]["design"]["schemaVersion"], 17)
        mock_run.assert_called_once_with(instructions="A welcome email for new signups")

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_name_override(self, mock_run):
        mock_run.return_value = ("```json\n{}\n```", json.dumps(GENERATED_TEMPLATE))

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email", "name": "My custom name"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["name"], "My custom name")

    def test_create_message_template_requires_instructions(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "instructions")

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_rejects_missing_subject(self, mock_run):
        without_subject = json.loads(json.dumps(GENERATED_TEMPLATE))
        del without_subject["content"]["email"]["subject"]
        mock_run.return_value = ("```json\n{}\n```", json.dumps(without_subject))

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(MessageTemplate.objects.exists())

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_forbidden_without_hog_flow_write_scope(self, mock_run):
        mock_run.return_value = ("```json\n{}\n```", json.dumps(GENERATED_TEMPLATE))
        api_key = self.create_personal_api_key_with_scopes(["hog_flow:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email"},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(MessageTemplate.objects.exists())

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_allowed_with_hog_flow_write_scope(self, mock_run):
        mock_run.return_value = ("```json\n{}\n```", json.dumps(GENERATED_TEMPLATE))
        api_key = self.create_personal_api_key_with_scopes(["hog_flow:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_persists_with_category(self, mock_run):
        mock_run.return_value = ("```json\n{}\n```", json.dumps(GENERATED_TEMPLATE))
        category = MessageCategory.objects.create(team=self.team, key="marketing", name="Marketing")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email", "message_category": str(category.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        template = MessageTemplate.objects.get(id=response.json()["id"])
        self.assertEqual(template.message_category_id, category.id)

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_rejects_cross_team_category(self, mock_run):
        mock_run.return_value = ("```json\n{}\n```", json.dumps(GENERATED_TEMPLATE))
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        foreign_category = MessageCategory.objects.create(team=other_team, key="marketing", name="Marketing")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email", "message_category": str(foreign_category.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(MessageTemplate.objects.exists())

    @patch.object(CreateMessageTemplateTool, "_run_impl")
    def test_create_message_template_generation_failure_returns_400(self, mock_run):
        mock_run.side_effect = PydanticOutputParserException(llm_output="", validation_message="bad output")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_message_template/",
            {"instructions": "A welcome email"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "instructions")
        self.assertFalse(MessageTemplate.objects.exists())
