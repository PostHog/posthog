import json
import os
from unittest.mock import ANY, patch
from inline_snapshot import snapshot
from rest_framework import status

from posthog.api.hog_function_template import HogFunctionTemplates
from posthog.cdp.templates.hog_function_template import derive_sub_templates
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from posthog.cdp.templates.slack.template_slack import template
from posthog.models import HogFunction
from django.core.cache import cache
from posthog.models.hog_function_template import HogFunctionTemplate as DBHogFunctionTemplate

MOCK_NODE_TEMPLATES = json.loads(
    open(os.path.join(os.path.dirname(__file__), "__data__/hog_function_templates.json")).read()
)

# NOTE: We check this as a sanity check given that this is a public API so we want to explicitly define what is exposed
EXPECTED_FIRST_RESULT = {
    "sub_templates": ANY,
    "free": template.free,
    "type": "destination",
    "status": template.status,
    "id": template.id,
    "name": template.name,
    "description": template.description,
    "hog": template.hog,
    "inputs_schema": template.inputs_schema,
    "category": template.category,
    "filters": template.filters,
    "masking": template.masking,
    "mappings": template.mappings,
    "mapping_templates": template.mapping_templates,
    "icon_url": template.icon_url,
    "kind": template.kind,
}


class TestHogFunctionTemplatesMixin(APIBaseTest):
    def test_derive_sub_templates(self):
        # One sanity check test (rather than all of them)
        sub_templates = derive_sub_templates([template])

        # check overridden params
        assert sub_templates[0].inputs_schema[-1]["key"] == "text"
        assert sub_templates[0].inputs_schema[-1]["default"] == snapshot(
            "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'"
        )
        assert sub_templates[0].filters == snapshot(
            {"events": [{"id": "$feature_enrollment_update", "type": "events"}]}
        )
        assert sub_templates[0].type == "destination"


class TestHogFunctionTemplates(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        with patch("posthog.api.hog_function_template.get_hog_function_templates") as mock_get_templates:
            mock_get_templates.return_value.status_code = 200
            mock_get_templates.return_value.json.return_value = MOCK_NODE_TEMPLATES
            HogFunctionTemplates._load_templates()  # Cache templates to simplify tests

    def test_list_function_templates(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) > 5
        assert EXPECTED_FIRST_RESULT in response.json()["results"]

    def test_filter_function_templates(self):
        response1 = self.client.get("/api/projects/@current/hog_function_templates/?type=notfound")
        assert response1.status_code == status.HTTP_200_OK, response1.json()
        assert len(response1.json()["results"]) == 0

        response2 = self.client.get("/api/projects/@current/hog_function_templates/?type=destination")
        response3 = self.client.get("/api/projects/@current/hog_function_templates/")

        assert response2.json()["results"] == response3.json()["results"]
        assert len(response2.json()["results"]) > 5

        response4 = self.client.get("/api/projects/@current/hog_function_templates/?type=site_destination")
        assert len(response4.json()["results"]) > 0

        response5 = self.client.get("/api/projects/@current/hog_function_templates/?types=site_destination,destination")
        assert len(response5.json()["results"]) > 0

    def test_filter_sub_templates(self):
        response1 = self.client.get(
            "/api/projects/@current/hog_function_templates/?type=internal_destination&sub_template_id=activity-log"
        )
        assert response1.status_code == status.HTTP_200_OK, response1.json()
        assert len(response1.json()["results"]) > 0

        template = response1.json()["results"][0]

        assert template["sub_templates"] is None
        assert template["type"] == "internal_destination"
        assert template["id"] == "template-slack-activity-log"

    def test_retrieve_function_template(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/template-slack")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == "template-slack"

    def test_retrieve_function_sub_template(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/template-slack-activity-log")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == "template-slack-activity-log"

    def test_public_list_function_templates(self):
        self.client.logout()
        response = self.client.get("/api/public_hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) > 5
        assert EXPECTED_FIRST_RESULT in response.json()["results"]

    def test_alpha_templates_are_hidden(self):
        self.client.logout()
        response = self.client.get("/api/public_hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        for template_item in response.json()["results"]:
            assert template_item["status"] != "alpha", f"Alpha template {template_item['id']} should not be returned"

    def test_templates_are_sorted_by_usage(self):
        HogFunction.objects.create(
            team=self.team,
            name="Test Function 1",
            template_id="template-slack",
            type="destination",
            enabled=True,
        )
        HogFunction.objects.create(
            team=self.team,
            name="Test Function 2",
            template_id="template-slack",
            type="destination",
            enabled=True,
        )
        HogFunction.objects.create(
            team=self.team,
            name="Test Function 3",
            template_id="template-webhook",
            type="destination",
            enabled=True,
        )

        cache.delete("hog_function/template_usage")

        response = self.client.get("/api/public_hog_function_templates/")
        assert response.status_code == status.HTTP_200_OK, response.json()

        results = response.json()["results"]
        assert results[0]["id"] == "template-slack"
        assert results[1]["id"] == "template-webhook"


class TestDatabaseHogFunctionTemplates(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()
        # Clear any existing templates
        DBHogFunctionTemplate.objects.all().delete()

        # Create some test templates in the database
        self.template1 = DBHogFunctionTemplate.create_from_dataclass(template)

        # Create a second version of the same template to test latest retrieval
        # We need to convert the sub_templates properly to ensure they're correctly structured
        sub_templates_json = []
        if template.sub_templates:
            for st in template.sub_templates:
                sub_template_dict = {
                    "id": st.id,
                    "name": st.name,
                    "description": st.description,
                    "type": st.type,  # Make sure we include the type field
                }
                # Include other fields that might be needed
                if hasattr(st, "filters") and st.filters:
                    sub_template_dict["filters"] = st.filters
                sub_templates_json.append(sub_template_dict)

        self.newer_template = DBHogFunctionTemplate.objects.create(
            template_id="template-slack",
            version="newer-version",
            name="Newer Slack",
            description="Updated Slack template",
            hog="return updated_event",
            inputs_schema=template.inputs_schema,
            type="destination",
            status="stable",
            category=["Customer Success"],
            free=True,
            sub_templates=sub_templates_json,
        )

        # Create a different template type
        self.webhook_template = DBHogFunctionTemplate.objects.create(
            template_id="template-webhook",
            version="1.0.0",
            name="Webhook",
            description="Generic webhook template",
            hog="return event",
            inputs_schema={},
            type="destination",
            status="stable",
            category=["Integrations"],
            free=True,
        )

        # Create a deprecated template
        self.deprecated_template = DBHogFunctionTemplate.objects.create(
            template_id="template-deprecated",
            version="1.0.0",
            name="Deprecated Template",
            description="A deprecated template",
            hog="return event",
            inputs_schema={},
            type="destination",
            status="deprecated",
            category=["Other"],
            free=True,
        )

    @patch("posthog.api.hog_function_template.settings")
    def test_get_templates_from_db(self, mock_settings):
        """Test retrieving templates from the database"""
        mock_settings.USE_DB_TEMPLATES = True

        # Test getting all templates
        templates = HogFunctionTemplates.templates()

        # Should have two templates (excluding deprecated)
        assert len(templates) == 2

        # Verify the templates are returned as DTOs
        template_ids = {t.id for t in templates}
        assert "template-slack" in template_ids
        assert "template-webhook" in template_ids
        assert "template-deprecated" not in template_ids

        # Verify we get the latest version of the template
        slack_template = next(t for t in templates if t.id == "template-slack")
        assert slack_template.name == "Newer Slack"

    @patch("posthog.api.hog_function_template.settings")
    def test_get_specific_template_from_db(self, mock_settings):
        """Test retrieving a specific template from the database"""
        mock_settings.USE_DB_TEMPLATES = True

        # Test getting a specific template
        slack_template = HogFunctionTemplates.template("template-slack")

        # Verify it's the newest version
        assert slack_template is not None
        assert slack_template.name == "Newer Slack"

        # Get all sub-templates first to verify they exist
        all_sub_templates = HogFunctionTemplates.sub_templates()
        assert len(all_sub_templates) > 0

        # Get one of the sub-templates that we know exists
        first_sub_template_id = all_sub_templates[0].id
        sub_template = HogFunctionTemplates.template(first_sub_template_id)

        # Verify the sub-template was found
        assert sub_template is not None
        assert sub_template.id == first_sub_template_id

        # Verify non-existent template returns None
        non_existent = HogFunctionTemplates.template("non-existent-template")
        assert non_existent is None

    @patch("posthog.api.hog_function_template.settings")
    def test_toggle_returns_in_memory_templates_when_off(self, mock_settings):
        """Test that in-memory templates are used when USE_DB_TEMPLATES is False"""
        # Setup: First create a distinct template in the DB with a unique name
        # that doesn't exist in the in-memory templates
        DBHogFunctionTemplate.objects.create(
            template_id="unique-db-template",
            version="1.0.0",
            name="Unique DB Template",
            description="This template only exists in the database",
            hog="return event",
            inputs_schema={},
            type="destination",
            status="stable",
            category=["Testing"],
            free=True,
        )

        # Mock the in-memory templates
        with patch("posthog.api.hog_function_template.get_hog_function_templates") as mock_get_templates:
            mock_get_templates.return_value.status_code = 200
            mock_get_templates.return_value.json.return_value = MOCK_NODE_TEMPLATES

            # 1. First test with USE_DB_TEMPLATES = True
            mock_settings.USE_DB_TEMPLATES = True

            # Get templates from database
            db_templates = HogFunctionTemplates.templates()

            # Verify our unique DB template is included
            db_template_ids = [t.id for t in db_templates]
            assert "unique-db-template" in db_template_ids

            # Get the specific template
            db_specific = HogFunctionTemplates.template("unique-db-template")
            assert db_specific is not None
            assert db_specific.name == "Unique DB Template"

            # 2. Now test with USE_DB_TEMPLATES = False
            mock_settings.USE_DB_TEMPLATES = False

            # Force reload of in-memory templates
            HogFunctionTemplates._cache_until = None

            # Get templates from in-memory
            memory_templates = HogFunctionTemplates.templates()

            # Verify our unique DB template is NOT included
            memory_template_ids = [t.id for t in memory_templates]
            assert "unique-db-template" not in memory_template_ids

            # Get the specific template - should be None since it only exists in DB
            memory_specific = HogFunctionTemplates.template("unique-db-template")
            assert memory_specific is None

            # But we should get the regular slack template from in-memory
            slack = HogFunctionTemplates.template("template-slack")
            assert slack is not None
            # Verify it's not the DB version (which has name "Newer Slack")
            assert slack.name != "Newer Slack"
