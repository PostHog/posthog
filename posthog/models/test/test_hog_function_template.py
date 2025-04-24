from django.test import TestCase

from posthog.cdp.templates.slack.template_slack import template as slack_template
from posthog.models.hog_function_template import HogFunctionTemplate


class TestHogFunctionTemplate(TestCase):
    def setUp(self):
        # Clean the database before every test
        HogFunctionTemplate.objects.all().delete()

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

        HogFunctionTemplate.objects.all().delete()

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

    def test_get_template(self):
        """Test retrieving templates by ID and version"""
        # Create two versions of the same template
        template1 = HogFunctionTemplate.objects.create(
            version="1.0.0",
            template_id="test-template",
            name="Test Template V1",
            description="First version",
            hog="return event",
            inputs_schema={},
            type="destination",
            status="alpha",
        )

        template2 = HogFunctionTemplate.objects.create(
            version="2.0.0",
            template_id="test-template",
            name="Test Template V2",
            description="Second version",
            hog="return null",
            inputs_schema={},
            type="destination",
            status="beta",
        )

        # Test getting a specific version
        retrieved_template = HogFunctionTemplate.get_template("test-template", "1.0.0")
        self.assertEqual(retrieved_template.id, template1.id)
        self.assertEqual(retrieved_template.name, "Test Template V1")

        # Test getting the latest version (by created_at)
        latest_template = HogFunctionTemplate.get_template("test-template")
        self.assertEqual(latest_template.id, template2.id)
        self.assertEqual(latest_template.name, "Test Template V2")

        # Test getting a non-existent template
        nonexistent_template = HogFunctionTemplate.get_template("non-existent-template")
        self.assertIsNone(nonexistent_template)
