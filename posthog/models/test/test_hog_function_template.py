from django.test import TestCase

from posthog.cdp.templates.slack.template_slack import template as slack_template
from posthog.models.hog_function_template import HogFunctionTemplate


class TestHogFunctionTemplate(TestCase):
    def setUp(self):
        # Clean the database before every test
        HogFunctionTemplate.objects.all().delete()

    def _create_template(
        self,
        template_id,
        version,
        name,
        status="alpha",
        type="destination",
        description=None,
        hog="return event",
        inputs_schema=None,
    ):
        """Helper method to create a template with common defaults"""
        return HogFunctionTemplate.objects.create(
            version=version,
            template_id=template_id,
            name=name,
            description=description or f"Description for {name}",
            hog=hog,
            inputs_schema=inputs_schema or {},
            type=type,
            status=status,
        )

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
        template1 = self._create_template(
            template_id="test-template",
            version="1.0.0",
            name="Test Template V1",
            description="First version",
            status="alpha",
        )

        template2 = self._create_template(
            template_id="test-template",
            version="2.0.0",
            name="Test Template V2",
            description="Second version",
            hog="return null",
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

    def test_get_latest_templates_excludes_deprecated(self):
        """Test that get_latest_templates filters out deprecated templates"""
        # Create active template
        self._create_template(
            template_id="active-template",
            version="1.0.0",
            name="Active Template",
            description="Active version",
            status="stable",
        )

        # Create deprecated template
        self._create_template(
            template_id="deprecated-template",
            version="1.0.0",
            name="Deprecated Template",
            description="Deprecated version",
            status="deprecated",
        )

        # Get latest templates excluding deprecated (default behavior)
        latest_templates = HogFunctionTemplate.get_latest_templates()
        template_ids = [template.template_id for template in latest_templates]

        # Check that only active template is included
        self.assertIn("active-template", template_ids)
        self.assertNotIn("deprecated-template", template_ids)

        # Get all templates including deprecated
        all_templates = HogFunctionTemplate.get_latest_templates(include_deprecated=True)
        all_template_ids = [template.template_id for template in all_templates]

        # Check that both templates are included
        self.assertIn("active-template", all_template_ids)
        self.assertIn("deprecated-template", all_template_ids)

    def test_get_latest_templates_multiple_versions(self):
        """Test that get_latest_templates correctly retrieves the latest version of each template"""
        import time

        # Create first versions
        self._create_template(
            template_id="template-a",
            version="1.0.0",
            name="Template A v1",
            description="First version of Template A",
            status="alpha",
        )

        self._create_template(
            template_id="template-b",
            version="1.0.0",
            name="Template B v1",
            description="First version of Template B",
            status="alpha",
        )

        # Ensure created_at timestamps will be different
        time.sleep(0.001)

        # Create second versions
        self._create_template(
            template_id="template-a",
            version="2.0.0",
            name="Template A v2",
            description="Second version of Template A",
            hog="return modified_event",
            inputs_schema={"updated": True},
            status="beta",
        )

        self._create_template(
            template_id="template-b",
            version="2.0.0",
            name="Template B v2",
            description="Second version of Template B",
            hog="return modified_event",
            inputs_schema={"updated": True},
            status="beta",
        )

        # Get latest templates
        latest_templates = HogFunctionTemplate.get_latest_templates()

        # Should have exactly 2 templates (latest version of each)
        self.assertEqual(len(latest_templates), 2)

        # Convert to dictionary for easier testing
        templates_dict = {t.template_id: t for t in latest_templates}

        # Check that we have the latest version of each template
        self.assertEqual(templates_dict["template-a"].version, "2.0.0")
        self.assertEqual(templates_dict["template-a"].name, "Template A v2")

        self.assertEqual(templates_dict["template-b"].version, "2.0.0")
        self.assertEqual(templates_dict["template-b"].name, "Template B v2")

        # Filter by type
        filtered_templates = HogFunctionTemplate.get_latest_templates(template_type="destination")
        self.assertEqual(len(filtered_templates), 2)

        # Create a different type template
        self._create_template(
            template_id="template-c",
            version="1.0.0",
            name="Template C",
            description="Different type template",
            type="transformation",
            status="stable",
        )

        # Filter by type should now return only the destination templates
        filtered_templates = HogFunctionTemplate.get_latest_templates(template_type="destination")
        self.assertEqual(len(filtered_templates), 2)

        # No filter should return all three templates (latest versions)
        all_templates = HogFunctionTemplate.get_latest_templates()
        self.assertEqual(len(all_templates), 3)
