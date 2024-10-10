from unittest.mock import ANY
from rest_framework import status

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from posthog.cdp.templates.slack.template_slack import template

# NOTE: We check this as a sanity check given that this is a public API so we want to explicitly define what is exposed
EXPECTED_FIRST_RESULT = {
    "sub_templates": ANY,
    "status": template.status,
    "id": template.id,
    "name": template.name,
    "description": template.description,
    "hog": template.hog,
    "inputs_schema": template.inputs_schema,
    "category": template.category,
    "filters": template.filters,
    "masking": template.masking,
    "icon_url": template.icon_url,
}


class TestHogFunctionTemplates(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_list_function_templates(self):
        response = self.client.get("/api/projects/@current/hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) > 5
        assert response.json()["results"][0] == EXPECTED_FIRST_RESULT

    def test_public_list_function_templates(self):
        self.client.logout()
        response = self.client.get("/api/public_hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) > 5
        assert response.json()["results"][0] == EXPECTED_FIRST_RESULT
