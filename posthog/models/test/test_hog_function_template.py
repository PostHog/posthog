from django.test import TestCase

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as slack_template
from posthog.models.hog_function_template import HogFunctionTemplate


class TestHogFunctionTemplate(TestCase):
    def setUp(self):
        # Clean the database before every test
        HogFunctionTemplate.objects.all().delete()

    def test_import_slack_template(self):
        """Test importing the real Slack template"""
        # Create a database template from the Slack template
        db_template = sync_template_to_db(slack_template)

        # Verify core fields
        self.assertEqual(db_template.template_id, "template-slack")
        self.assertEqual(db_template.name, "Slack")
        self.assertEqual(db_template.description, "Sends a message to a Slack channel")
        self.assertEqual(db_template.type, "destination")
        self.assertEqual(db_template.status, "stable")
        self.assertEqual(db_template.category, ["Customer Success"])
        self.assertEqual(db_template.free, True)

        # Verify sha is generated correctly
        self.assertIsNotNone(db_template.sha)
        self.assertEqual(len(db_template.sha), 8)  # SHA hash truncated to 8 chars

        HogFunctionTemplate.objects.all().delete()

        # Verify the sha is deterministic by creating another instance
        db_template2 = sync_template_to_db(slack_template)
        self.assertEqual(db_template.sha, db_template2.sha)

        # Verify bytecode was compiled
        self.assertIsNotNone(db_template.bytecode)

        # Convert back to dataclass and verify structure is preserved
        self.assertEqual(db_template.template_id, "template-slack")
        self.assertEqual(db_template.name, "Slack")

    def test_get_template_by_id_and_sha(self):
        """Test retrieving templates by ID and sha"""
        # Create template with a specific sha
        template = HogFunctionTemplate.objects.create(
            template_id="test-template",
            sha="1.0.0",
            name="Test Template",
            description="Template description",
            status="alpha",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )

        # Test getting by ID and sha
        retrieved_template = HogFunctionTemplate.get_template("test-template", template.sha)
        assert retrieved_template
        self.assertEqual(retrieved_template.template_id, template.template_id)
        self.assertEqual(retrieved_template.name, "Test Template")

        # Test getting by ID without sha (should get the template)
        latest_template = HogFunctionTemplate.get_template("test-template")
        assert latest_template
        self.assertEqual(latest_template.template_id, template.template_id)

        # Test getting a non-existent template
        nonexistent_template = HogFunctionTemplate.get_template("non-existent-template")
        assert nonexistent_template is None

    def test_update_existing_template(self):
        """Test updating an existing template with new content"""
        from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

        # First create a simple template
        original_dto = HogFunctionTemplateDC(
            id="update-test",
            name="Original Template",
            code="return event",
            inputs_schema=[{"field": "value"}],
            status="alpha",
            type="destination",
            free=True,
            category=["Testing"],
            code_language="hog",
        )

        # Create the template in the database
        original_template = sync_template_to_db(original_dto)
        original_sha = original_template.sha

        # Now create an updated sha of the same template
        updated_dto = HogFunctionTemplateDC(
            id="update-test",  # Same ID
            name="Updated Template",  # Changed
            code="return {...event, updated: true}",  # Changed
            inputs_schema=[{"field": "value", "new_field": "new_value"}],  # Changed
            status="beta",  # Changed
            type="destination",
            free=True,
            category=["Testing", "Updated"],  # Changed
            code_language="hog",
        )

        # Update the template
        updated_template = sync_template_to_db(updated_dto)
        self.assertNotEqual(updated_template.sha, original_sha, "SHA should change when content changes")

        # Verify the template was updated
        self.assertEqual(updated_template.template_id, "update-test")
        self.assertEqual(updated_template.name, "Updated Template")
        self.assertEqual(updated_template.status, "beta")
        self.assertEqual(updated_template.category, ["Testing", "Updated"])

        # Check database to ensure only one template exists with this ID
        templates = HogFunctionTemplate.objects.filter(template_id="update-test")
        self.assertEqual(templates.count(), 1, "Only one template should exist with this ID")

        # Now updating with the same content shouldn't change the sha
        same_updated_template = sync_template_to_db(updated_dto)
        self.assertEqual(
            same_updated_template.sha,
            updated_template.sha,
            "SHA should not change when content is the same",
        )

    def test_get_latest_templates(self):
        """Test the get_latest_templates method with various filters and options"""
        # Create templates with various statuses
        HogFunctionTemplate.objects.create(
            template_id="active-template",
            sha="1.0.0",
            name="Active Template",
            status="stable",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )

        HogFunctionTemplate.objects.create(
            template_id="deprecated-template",
            sha="1.0.0",
            name="Deprecated Template",
            status="deprecated",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )

        # Create templates with different types
        HogFunctionTemplate.objects.create(
            template_id="template-a",
            sha="1.0.0",
            name="Template A",
            status="alpha",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )

        HogFunctionTemplate.objects.create(
            template_id="template-b",
            sha="1.0.0",
            name="Template B",
            status="beta",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )

        # Create a different type template
        HogFunctionTemplate.objects.create(
            template_id="template-c",
            sha="1.0.0",
            name="Template C",
            type="transformation",
            status="stable",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )

        # TEST 1: Excluding deprecated templates (default)
        latest_templates = HogFunctionTemplate.get_latest_templates()
        template_ids = [template.template_id for template in latest_templates]

        # Active templates should be included, deprecated should not
        self.assertIn("active-template", template_ids)
        self.assertNotIn("deprecated-template", template_ids)

        # TEST 2: Including deprecated templates
        all_templates = HogFunctionTemplate.get_latest_templates(include_deprecated=True)
        all_template_ids = [template.template_id for template in all_templates]

        # Both active and deprecated templates should be included
        self.assertIn("active-template", all_template_ids)
        self.assertIn("deprecated-template", all_template_ids)

        # TEST 3: Filtering by type
        destination_templates = HogFunctionTemplate.get_latest_templates(template_type="destination")
        transformation_templates = HogFunctionTemplate.get_latest_templates(template_type="transformation")

        # Check correct counts by type
        self.assertEqual(len(destination_templates), 3)  # active, template-a, template-b
        self.assertEqual(len(transformation_templates), 1)  # template-c

        # Check specific templates
        destination_ids = [t.template_id for t in destination_templates]
        self.assertIn("template-a", destination_ids)
        self.assertIn("template-b", destination_ids)
        self.assertNotIn("template-c", destination_ids)

        transformation_ids = [t.template_id for t in transformation_templates]
        self.assertIn("template-c", transformation_ids)
        self.assertNotIn("template-a", transformation_ids)

    def test_sha_versioning(self):
        template = HogFunctionTemplate(
            template_id="template-c",
            sha="1.0.0",
            name="Template C",
            type="transformation",
            status="stable",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )
        self.assertEqual(len(template._generate_sha_from_content()), 8)
        original_sha = template.sha

        template.code = "return event"
        assert template._generate_sha_from_content() == original_sha

        template.code = "return modified_event"
        assert template._generate_sha_from_content() != original_sha

        template.code = "return event"
        template.status = "beta"
        assert template._generate_sha_from_content() != original_sha
