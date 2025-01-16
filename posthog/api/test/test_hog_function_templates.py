from unittest.mock import ANY
from inline_snapshot import snapshot
from rest_framework import status

from posthog.cdp.templates.hog_function_template import derive_sub_templates
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
        assert response.json()["results"][0] == EXPECTED_FIRST_RESULT

    def test_alpha_templates_are_hidden(self):
        self.client.logout()
        response = self.client.get("/api/public_hog_function_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        for template_item in response.json()["results"]:
            assert template_item["status"] != "alpha", f"Alpha template {template_item['id']} should not be returned"
            assert (
                "[CDP-TEST-HIDDEN]" not in template_item["name"]
            ), f"Test template {template_item['id']} should not be returned"
