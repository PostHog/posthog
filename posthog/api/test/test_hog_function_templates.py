from unittest.mock import ANY
from rest_framework import status

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from posthog.cdp.templates.slack.template_slack import template

# NOTE: We check this as a sanity check given that this is a public API so we want to explicitly define what is exposed
EXPECTED_FIRST_RESULT = {
    "sub_templates": ANY,
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
    def test_list_function_templates(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) > 5
        assert response.json()["results"][0] == EXPECTED_FIRST_RESULT

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
            "/api/projects/@current/hog_function_templates/?type=internal_destination&sub_template_id=activity_log"
        )
        assert response1.status_code == status.HTTP_200_OK, response1.json()
        assert len(response1.json()["results"]) == 1

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
        assert response.json()["results"][0] == EXPECTED_FIRST_RESULT
