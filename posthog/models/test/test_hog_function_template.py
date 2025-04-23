from django.test import TestCase

from posthog.cdp.templates.slack.template_slack import template as slack_template
from posthog.models.hog_function_template import HogFunctionTemplate


class TestHogFunctionTemplate(TestCase):
    def test_import_slack_template(self):
        """Test importing the real Slack template"""
        # Create a database template from the Slack template
        db_template = HogFunctionTemplate.create_from_dataclass(slack_template)

        # Verify core fields
        self.assertEqual(db_template.template_id, "template-slack")
        self.assertEqual(db_template.name, "Slack")
        self.assertEqual(db_template.description, "Sends a message to a Slack channel")
        self.assertEqual(db_template.type, "destination")
        self.assertEqual(db_template.status, "stable")
        self.assertEqual(db_template.category, ["Customer Success"])
        self.assertEqual(db_template.free, True)

        # Verify version is generated correctly
        self.assertIsNotNone(db_template.version)
        self.assertEqual(len(db_template.version), 8)  # SHA hash truncated to 8 chars

        # Verify the version is deterministic by creating another instance
        db_template2 = HogFunctionTemplate.create_from_dataclass(slack_template)
        self.assertEqual(db_template.version, db_template2.version)

        # Verify sub-templates
        self.assertIsNotNone(db_template.sub_templates)
        self.assertEqual(len(db_template.sub_templates), 5)

        # Check a specific sub-template
        survey_sub_template = next((st for st in db_template.sub_templates if st["id"] == "survey-response"), None)
        self.assertIsNotNone(survey_sub_template)
        self.assertEqual(survey_sub_template["name"], "Post to Slack on survey response")

        # Verify bytecode was compiled
        self.assertIsNotNone(db_template.bytecode)

        # Convert back to dataclass and verify structure is preserved
        dataclass_template = db_template.to_dataclass()
        self.assertEqual(dataclass_template.id, "template-slack")
        self.assertEqual(dataclass_template.name, "Slack")

        # Verify sub-templates in dataclass
        self.assertIsNotNone(dataclass_template.sub_templates)
        self.assertEqual(len(dataclass_template.sub_templates), 5)

        # Check a specific sub-template in dataclass
        survey_sub_template_dto = next(
            (st for st in dataclass_template.sub_templates if st.id == "survey-response"), None
        )
        self.assertIsNotNone(survey_sub_template_dto)
        self.assertEqual(survey_sub_template_dto.name, "Post to Slack on survey response")
