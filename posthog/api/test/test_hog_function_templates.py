import json
import os
from unittest.mock import patch
from rest_framework import status

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
}


class TestHogFunctionTemplates(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        # Clear any existing templates and create test templates in the database
        DBHogFunctionTemplate.objects.all().delete()

        # Create test templates that the tests expect
        self.template1, _ = DBHogFunctionTemplate.create_from_dataclass(template)

        # Create a webhook template
        self.webhook_template = DBHogFunctionTemplate.objects.create(
            template_id="template-webhook",
            sha="1.0.0",
            name="Webhook",
            description="Generic webhook template",
            code="return event",
            code_language="hog",
            inputs_schema={},
            type="destination",
            status="stable",
            category=["Integrations"],
            free=True,
        )

        # Create additional templates to ensure we have > 5 templates
        for i in range(4):
            DBHogFunctionTemplate.objects.create(
                template_id=f"template-test-{i}",
                sha="1.0.0",
                name=f"Test Template {i}",
                description=f"Test template {i}",
                code="return event",
                code_language="hog",
                inputs_schema={},
                type="destination",
                status="stable",
                category=["Testing"],
                free=True,
            )

        # Create a site_destination template for filtering tests
        DBHogFunctionTemplate.objects.create(
            template_id="template-site-destination",
            sha="1.0.0",
            name="Site Destination",
            description="Site destination template",
            code="return event",
            code_language="hog",
            inputs_schema={},
            type="site_destination",
            status="stable",
            category=["Testing"],
            free=True,
        )

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

    def test_retrieve_function_template(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/template-slack")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == "template-slack"

    def test_public_list_function_templates(self):
        self.client.logout()
        response = self.client.get("/api/public_hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) > 5

    def test_hidden_templates_are_hidden(self):
        self.client.logout()
        response = self.client.get("/api/public_hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        for template_item in response.json()["results"]:
            assert template_item["status"] != "hidden", f"Hidden template {template_item['id']} should not be returned"

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

        # Create test templates in the database
        self.template1, _ = DBHogFunctionTemplate.create_from_dataclass(template)

        # Create a different template type
        self.webhook_template = DBHogFunctionTemplate.objects.create(
            template_id="template-webhook",
            sha="1.0.0",
            name="Webhook",
            description="Generic webhook template",
            code="return event",
            code_language="hog",
            inputs_schema={},
            type="destination",
            status="stable",
            category=["Integrations"],
            free=True,
        )

        # Create a deprecated template
        self.deprecated_template = DBHogFunctionTemplate.objects.create(
            template_id="template-deprecated",
            sha="1.0.0",
            name="Deprecated Template",
            description="A deprecated template",
            code="return event",
            code_language="hog",
            inputs_schema={},
            type="destination",
            status="deprecated",
            category=["Other"],
            free=True,
        )

    @patch("posthog.api.hog_function_template.get_hog_function_templates")
    def test_get_templates_from_db(self, mock_get_templates):
        """Test retrieving templates from the database via API"""
        mock_get_templates.return_value.status_code = 200
        mock_get_templates.return_value.json.return_value = MOCK_NODE_TEMPLATES

        # Test getting templates via API endpoint
        response = self.client.get("/api/projects/@current/hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]

        # Find the template IDs in the response
        template_ids = {t["id"] for t in results}

        # Check that we have the expected templates and not the deprecated one
        assert "template-slack" in template_ids
        assert "template-webhook" in template_ids
        assert "template-deprecated" not in template_ids

        # Verify slack template has the right name
        slack_template = next(t for t in results if t["id"] == "template-slack")
        assert slack_template["name"] == template.name  # Name should match the original template

    def test_get_specific_template_from_db(self):
        """Test retrieving a specific template from the database via API"""
        # Test getting a specific template via API endpoint
        response = self.client.get(f"/api/projects/@current/hog_function_templates/template-slack")

        assert response.status_code == status.HTTP_200_OK, response.json()
        # Verify it has the expected name
        assert response.json()["name"] == template.name

    def test_get_specific_missing_template_from_db(self):
        """Test retrieving a specific template from the database via API"""
        # Verify non-existent template returns 404
        response_missing = self.client.get("/api/projects/@current/hog_function_templates/non-existent-template")
        assert response_missing.status_code == status.HTTP_404_NOT_FOUND

    def test_get_specific_deprecated_template_from_db(self):
        """Test retrieving a specific template from the database via API"""
        # Test getting a specific template via API endpoint
        response = self.client.get(f"/api/projects/@current/hog_function_templates/template-deprecated")

        assert response.status_code == status.HTTP_200_OK, response.json()
        # Verify it has the expected name
        assert response.json()["name"] == self.deprecated_template.name

    def test_template_updates_are_reflected(self):
        """Test that template updates are reflected in API responses"""
        from posthog.cdp.templates.hog_function_template import HogFunctionTemplate as DataclassTemplate

        # Initial sha of the template
        initial_response = self.client.get("/api/projects/@current/hog_function_templates/template-slack")
        assert initial_response.status_code == status.HTTP_200_OK
        assert initial_response.json()["name"] == template.name

        # Create a modified sha of the template
        modified_template = DataclassTemplate(
            id="template-slack",  # Same ID
            name="Updated Slack",  # Changed
            description="This template was updated",  # Changed
            type="destination",
            hog="return {...event, updated: true}",  # Changed
            inputs_schema=template.inputs_schema,
            status="stable",
            free=True,
            category=["Customer Success"],
        )

        # Save the modified template - this should update the existing one
        DBHogFunctionTemplate.create_from_dataclass(modified_template)

        # Get the template again and check it was updated
        updated_response = self.client.get("/api/projects/@current/hog_function_templates/template-slack")
        assert updated_response.status_code == status.HTTP_200_OK
        assert updated_response.json()["name"] == "Updated Slack"
        assert updated_response.json()["description"] == "This template was updated"

    def test_always_uses_database_templates(self):
        """Test that templates are always loaded from database"""
        # Create a unique template in the DB
        DBHogFunctionTemplate.objects.create(
            template_id="unique-db-template",
            sha="1.0.0",
            name="Unique DB Template",
            description="This template only exists in the database",
            code="return event",
            code_language="hog",
            inputs_schema={},
            type="destination",
            status="stable",
            category=["Testing"],
            free=True,
        )

        # Test that the template is always returned from database
        response = self.client.get("/api/projects/@current/hog_function_templates/")
        assert response.status_code == status.HTTP_200_OK, response.json()

        # Verify our unique DB template is included
        template_ids = [t["id"] for t in response.json()["results"]]
        assert "unique-db-template" in template_ids

        # Get the specific template via API
        response_specific = self.client.get("/api/projects/@current/hog_function_templates/unique-db-template")
        assert response_specific.status_code == status.HTTP_200_OK, response_specific.json()
        assert response_specific.json()["name"] == "Unique DB Template"
