from django.test import TestCase
from typing import Literal, Any, Optional, cast

from posthog.cdp.templates.slack.template_slack import template as slack_template
from posthog.models.hog_function_template import HogFunctionTemplate


class TestHogFunctionTemplate(TestCase):
    def setUp(self):
        # Clean the database before every test
        HogFunctionTemplate.objects.all().delete()

    def _create_template(
        self,
        template_id: str,
        sha: str,
        name: str,
        status: Literal["alpha", "beta", "stable", "deprecated"] = "alpha",
        type: str = "destination",
        description: Optional[str] = None,
        code: str = "return event",
        code_language: str = "hog",
        inputs_schema: Optional[list[dict[str, Any]]] = None,
    ):
        """Helper method to create a template with common defaults"""
        return HogFunctionTemplate.objects.create(
            sha=sha,
            template_id=template_id,
            name=name,
            description=description or f"Description for {name}",
            code=code,
            code_language=code_language,
            inputs_schema=inputs_schema or [{}],
            type=type,
            status=cast(Literal["alpha", "beta", "stable", "deprecated"], status),
        )

    def test_import_slack_template(self):
        """Test importing the real Slack template"""
        # Create a database template from the Slack template
        db_template, _ = HogFunctionTemplate.create_from_dataclass(slack_template)

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
        db_template2, _ = HogFunctionTemplate.create_from_dataclass(slack_template)
        self.assertEqual(db_template.sha, db_template2.sha)

        # Verify bytecode was compiled
        self.assertIsNotNone(db_template.bytecode)

        # Convert back to dataclass and verify structure is preserved
        dataclass_template = db_template.to_dataclass()
        self.assertEqual(dataclass_template.id, "template-slack")
        self.assertEqual(dataclass_template.name, "Slack")

    def test_get_template_by_id_and_sha(self):
        """Test retrieving templates by ID and sha"""
        # Create template with a specific sha
        template = self._create_template(
            template_id="test-template",
            sha="1.0.0",
            name="Test Template",
            description="Template description",
            status="alpha",
            code="return event",
            code_language="hog",
        )

        # Test getting by ID and sha
        retrieved_template = HogFunctionTemplate.get_template("test-template", "1.0.0")
        self.assertEqual(retrieved_template.id, template.id)
        self.assertEqual(retrieved_template.name, "Test Template")

        # Test getting by ID without sha (should get the template)
        latest_template = HogFunctionTemplate.get_template("test-template")
        self.assertEqual(latest_template.id, template.id)

        # Test getting a non-existent template
        nonexistent_template = HogFunctionTemplate.get_template("non-existent-template")
        self.assertIsNone(nonexistent_template)

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
        original_template, created = HogFunctionTemplate.create_from_dataclass(original_dto)
        self.assertTrue(created, "Template should be created")
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
        updated_template, created = HogFunctionTemplate.create_from_dataclass(updated_dto)
        self.assertFalse(created, "Template should be updated, not created")
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
        same_updated_template, created = HogFunctionTemplate.create_from_dataclass(updated_dto)
        self.assertFalse(created, "Template should not be re-created")
        self.assertEqual(
            same_updated_template.sha,
            updated_template.sha,
            "SHA should not change when content is the same",
        )

    def test_get_latest_templates(self):
        """Test the get_latest_templates method with various filters and options"""
        # Create templates with various statuses
        self._create_template(
            template_id="active-template",
            sha="1.0.0",
            name="Active Template",
            status="stable",
            code="return event",
            code_language="hog",
        )

        self._create_template(
            template_id="deprecated-template",
            sha="1.0.0",
            name="Deprecated Template",
            status="deprecated",
            code="return event",
            code_language="hog",
        )

        # Create templates with different types
        self._create_template(
            template_id="template-a",
            sha="1.0.0",
            name="Template A",
            status="alpha",
            code="return event",
            code_language="hog",
        )

        self._create_template(
            template_id="template-b",
            sha="1.0.0",
            name="Template B",
            status="beta",
            code="return event",
            code_language="hog",
        )

        # Create a different type template
        self._create_template(
            template_id="template-c",
            sha="1.0.0",
            name="Template C",
            type="transformation",
            status="stable",
            code="return event",
            code_language="hog",
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
        """Test template sha versioning system including status and related fields"""
        from posthog.cdp.templates.hog_function_template import (
            HogFunctionTemplateDC,
            HogFunctionMapping,
            HogFunctionMappingTemplate,
        )

        # Test 1: Basic sha generation
        # Test empty content
        empty_sha = HogFunctionTemplate.generate_sha_from_content("")
        self.assertEqual(len(empty_sha), 8)

        # Test identical content produces identical shas
        content1 = "return event"
        content2 = "return event"

        sha1 = HogFunctionTemplate.generate_sha_from_content(content1)
        sha2 = HogFunctionTemplate.generate_sha_from_content(content2)

        self.assertEqual(sha1, sha2)

        # Test different content produces different shas
        content3 = "return modified_event"
        sha3 = HogFunctionTemplate.generate_sha_from_content(content3)

        self.assertNotEqual(sha1, sha3)

        # Test 2: Status change creates new sha
        template_alpha = HogFunctionTemplateDC(
            id="test-status-template",
            name="Test Template",
            code="return event",
            inputs_schema=[],
            status="alpha",
            type="destination",
            free=True,
            category=[],
            code_language="hog",
        )

        template_beta = HogFunctionTemplateDC(
            id="test-status-template",
            name="Test Template",
            code="return event",
            inputs_schema=[],
            status="beta",
            type="destination",
            free=True,
            category=[],
            code_language="hog",
        )

        # Create first sha
        db_template_alpha, created_alpha = HogFunctionTemplate.create_from_dataclass(template_alpha)
        self.assertTrue(created_alpha)

        # Update with new status - should change sha but not create new record
        db_template_beta, created_beta = HogFunctionTemplate.create_from_dataclass(template_beta)
        self.assertFalse(created_beta)
        self.assertNotEqual(db_template_alpha.sha, db_template_beta.sha)

        # Verify only one template exists
        templates = HogFunctionTemplate.objects.filter(template_id="test-status-template")
        self.assertEqual(templates.count(), 1)

        # Test 3: Changes to related fields create new shas
        base_template = HogFunctionTemplateDC(
            id="advanced-template",
            name="Advanced Template",
            code="return event",
            inputs_schema=[],
            status="stable",
            type="destination",
            free=True,
            category=[],
            code_language="hog",
        )

        # Create template with mappings
        template_with_mappings = HogFunctionTemplateDC(
            id="advanced-template",
            name="Advanced Template",
            code="return event",
            inputs_schema=[],
            status="stable",
            type="destination",
            free=True,
            category=[],
            mappings=[HogFunctionMapping()],
            code_language="hog",
        )

        # Create base template first
        db_base, created_base = HogFunctionTemplate.create_from_dataclass(base_template)
        self.assertTrue(created_base)

        # Update with mappings
        db_mappings, created_mappings = HogFunctionTemplate.create_from_dataclass(template_with_mappings)
        self.assertFalse(created_mappings)
        self.assertNotEqual(db_base.sha, db_mappings.sha, "Adding mappings should change sha")

        # Verify only one template exists with this ID
        templates = HogFunctionTemplate.objects.filter(template_id="advanced-template")
        self.assertEqual(templates.count(), 1)

        # Create template with filters
        template_with_filters = HogFunctionTemplateDC(
            id="advanced-template",
            name="Advanced Template",
            code="return event",
            inputs_schema=[],
            status="stable",
            type="destination",
            free=True,
            category=[],
            filters={"events": [{"id": "$pageview"}]},
            code_language="hog",
        )

        # Update with filters
        db_filters, created_filters = HogFunctionTemplate.create_from_dataclass(template_with_filters)
        self.assertFalse(created_filters)
        self.assertNotEqual(db_mappings.sha, db_filters.sha, "Adding filters should change sha")

        # Create template with mapping_templates
        template_with_mapping_templates = HogFunctionTemplateDC(
            id="advanced-template",
            name="Advanced Template",
            code="return event",
            inputs_schema=[],
            status="stable",
            type="destination",
            free=True,
            category=[],
            mapping_templates=[HogFunctionMappingTemplate(name="Mapping Template 1")],
            code_language="hog",
        )

        # Update with mapping templates
        db_mapping_templates, created_mapping_templates = HogFunctionTemplate.create_from_dataclass(
            template_with_mapping_templates
        )
        self.assertFalse(created_mapping_templates)
        self.assertNotEqual(db_filters.sha, db_mapping_templates.sha, "Adding mapping_templates should change sha")

        # Check total template count remains at 1
        templates = HogFunctionTemplate.objects.filter(template_id="advanced-template")
        self.assertEqual(templates.count(), 1, "Only one template should exist with this ID despite multiple updates")

    def test_dataclass_conversion_roundtrip(self):
        """Test converting between database model and dataclass representation"""
        from posthog.cdp.templates.hog_function_template import (
            HogFunctionMapping,
        )

        # Create a complex template with mappings
        template = HogFunctionTemplate.objects.create(
            template_id="complex-template",
            sha="1.0.0",
            name="Complex Template",
            description="Template with mappings",
            code="return event",
            code_language="hog",
            inputs_schema=[{"key": "value"}],
            type="destination",
            status=cast(Literal["alpha", "beta", "stable", "deprecated"], "stable"),
            category=["Integration", "Analytics"],
            free=True,
            mappings=[{"filters": {"event": "$pageview"}, "inputs": {"message": "Page viewed"}}],
        )

        # Convert to dataclass
        dataclass_template = template.to_dataclass()

        # Verify fields were converted correctly
        self.assertEqual(dataclass_template.id, "complex-template")
        self.assertEqual(dataclass_template.name, "Complex Template")
        self.assertEqual(dataclass_template.description, "Template with mappings")
        self.assertEqual(dataclass_template.inputs_schema, [{"key": "value"}])
        self.assertEqual(dataclass_template.category, ["Integration", "Analytics"])
        self.assertEqual(dataclass_template.free, True)

        # Verify mappings were converted to proper objects
        mappings = dataclass_template.mappings or []
        self.assertEqual(len(mappings), 1)
        self.assertTrue(isinstance(mappings[0], HogFunctionMapping))
        self.assertEqual(mappings[0].filters, {"event": "$pageview"})
        self.assertEqual(mappings[0].inputs, {"message": "Page viewed"})

        # Convert back to database model
        new_template, _ = HogFunctionTemplate.create_from_dataclass(dataclass_template)

        # Verify fields were preserved through the roundtrip
        self.assertEqual(new_template.template_id, template.template_id)
        self.assertEqual(new_template.name, template.name)
        self.assertEqual(new_template.description, template.description)
        self.assertEqual(new_template.type, template.type)
        self.assertEqual(new_template.category, template.category)

        # Verify mappings were preserved
        self.assertEqual(len(new_template.mappings or []), 1)
        mappings = new_template.mappings or []
        if mappings and isinstance(mappings[0], dict):
            self.assertEqual(mappings[0]["filters"], {"event": "$pageview"})
            self.assertEqual(mappings[0]["inputs"], {"message": "Page viewed"})
