import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from rest_framework import status

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import HogFunction
from posthog.models.hog_function_template import HogFunctionTemplate

MOCK_NODE_TEMPLATES = json.loads(
    open(os.path.join(os.path.dirname(__file__), "__data__/hog_function_templates.json")).read()
)

# NOTE: We check this as a sanity check given that this is a public API so we want to explicitly define what is exposed
EXPECTED_FIRST_RESULT = {
    "free": template_slack.free,
    "type": "destination",
    "code_language": template_slack.code_language,
    "status": template_slack.status,
    "id": template_slack.id,
    "name": template_slack.name,
    "description": template_slack.description,
    "code": template_slack.code,
    "inputs_schema": template_slack.inputs_schema,
    "category": template_slack.category,
    "filters": template_slack.filters,
    "masking": template_slack.masking,
    "mapping_templates": template_slack.mapping_templates,
    "icon_url": template_slack.icon_url,
}


class TestHogFunctionTemplates(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        # Clear any existing templates and create test templates in the database
        HogFunctionTemplate.objects.all().delete()

        # Create test templates that the tests expect
        self.template1 = sync_template_to_db(template_slack)

        # Create a webhook template
        self.webhook_template = HogFunctionTemplate.objects.create(
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
        self.deprecated_template = HogFunctionTemplate.objects.create(
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

        # Create additional templates to ensure we have > 5 templates
        for i in range(4):
            HogFunctionTemplate.objects.create(
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
        HogFunctionTemplate.objects.create(
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
        assert EXPECTED_FIRST_RESULT == response.json()["results"][0]

    def test_deprecated_templates_are_not_included(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "template-deprecated" not in [template["id"] for template in response.json()["results"]]

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
        assert response.json()["type"] == "destination"

    def test_retrieve_function_template_with_other_type(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/template-site-destination")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == "template-site-destination"
        assert response.json()["type"] == "site_destination"

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

    def test_get_specific_deprecated_template_from_db(self):
        """Test retrieving a specific template from the database via API"""
        # Test getting a specific template via API endpoint
        response = self.client.get(f"/api/projects/@current/hog_function_templates/template-deprecated")

        assert response.status_code == status.HTTP_200_OK, response.json()
        # Verify it has the expected name
        assert response.json()["name"] == self.deprecated_template.name

    def test_template_updates_are_reflected(self):
        """Test that template updates are reflected in API responses"""
        from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

        # Initial sha of the template
        initial_response = self.client.get("/api/projects/@current/hog_function_templates/template-slack")
        assert initial_response.status_code == status.HTTP_200_OK
        assert initial_response.json()["name"] == template_slack.name

        # Create a modified sha of the template
        modified_template = HogFunctionTemplateDC(
            id="template-slack",  # Same ID
            name="Updated Slack",  # Changed
            description="This template was updated",  # Changed
            type="destination",
            code="return {...event, updated: true}",  # Changed
            inputs_schema=template_slack.inputs_schema,
            status="stable",
            free=True,
            category=["Customer Success"],
            code_language="hog",
        )

        # Save the modified template - this should update the existing one
        sync_template_to_db(modified_template)

        # Get the template again and check it was updated
        updated_response = self.client.get("/api/projects/@current/hog_function_templates/template-slack")
        assert updated_response.status_code == status.HTTP_200_OK
        assert updated_response.json()["name"] == "Updated Slack"
        assert updated_response.json()["description"] == "This template was updated"

    def test_public_hog_function_templates_are_sorted_by_usage(self):
        for i in range(10):
            HogFunction.objects.create(
                team=self.team,
                name=f"Test Function {i}",
                template_id="template-slack",
                type="destination",
                enabled=True,
            )

        HogFunction.objects.create(
            team=self.team,
            name="Test Function 1",
            template_id="template-test-2",
            type="destination",
            enabled=True,
        )

        response = self.client.get("/api/public_hog_function_templates/")
        assert response.status_code == status.HTTP_200_OK, response.json()

        results = response.json()["results"]
        assert results[0]["id"] == "template-slack"
        assert results[1]["id"] == "template-test-2"
        assert results[2]["id"] == "template-test-0"
