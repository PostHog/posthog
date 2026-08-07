from django.test import TestCase

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, sync_template_to_db

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate


class TestHogFunctionTemplate(TestCase):
    def setUp(self):
        # Clean the database before every test
        HogFunctionTemplate.objects.all().delete()

    def test_sync_template_to_db_round_trips_fields(self):
        dto = HogFunctionTemplateDC(
            id="template-sync-test",
            name="Sync Test",
            description="Round trips through the serializer",
            code="return event",
            inputs_schema=[{"key": "url", "type": "string"}],
            status="stable",
            type="destination",
            free=True,
            category=["Testing"],
            code_language="hog",
        )

        db_template = sync_template_to_db(dto)

        self.assertEqual(db_template.template_id, "template-sync-test")
        self.assertEqual(db_template.name, "Sync Test")
        self.assertEqual(db_template.description, "Round trips through the serializer")
        self.assertEqual(db_template.type, "destination")
        self.assertEqual(db_template.status, "stable")
        self.assertEqual(db_template.category, ["Testing"])
        self.assertEqual(db_template.free, True)
        self.assertEqual(len(db_template.sha), 8)
        self.assertIsNotNone(db_template.bytecode)

        HogFunctionTemplate.objects.all().delete()

        # A fresh sync of unchanged content must land on the same sha, or every deploy
        # would write a new row and pin existing functions to a stale one.
        self.assertEqual(sync_template_to_db(dto).sha, db_template.sha)

    def test_get_template_by_id_and_sha(self):
        """Test retrieving templates by ID and sha"""
        # Create template with a specific sha
        template = HogFunctionTemplate.objects.create(
            template_id="test-template",
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

    def test_sha_versioning(self):
        template = HogFunctionTemplate(
            template_id="template-c",
            name="Template C",
            type="transformation",
            status="stable",
            code="return event",
            code_language="hog",
            inputs_schema=[],
        )
        original_sha = template._generate_sha_from_content()
        self.assertEqual(len(original_sha), 8)

        template.code = "return event"
        assert template._generate_sha_from_content() == original_sha

        template.code = "return modified_event"
        assert template._generate_sha_from_content() != original_sha

        template.code = "return event"
        template.status = "beta"
        assert template._generate_sha_from_content() != original_sha
