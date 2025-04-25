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
        db_template, _ = HogFunctionTemplate.create_from_dataclass(slack_template)

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
        db_template2, _ = HogFunctionTemplate.create_from_dataclass(slack_template)
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

    def test_get_template_by_id_and_version(self):
        """Test retrieving templates by ID and version"""
        # Create template with a specific version
        template = self._create_template(
            template_id="test-template",
            version="1.0.0",
            name="Test Template",
            description="Template description",
            status="alpha",
        )

        # Test getting by ID and version
        retrieved_template = HogFunctionTemplate.get_template("test-template", "1.0.0")
        self.assertEqual(retrieved_template.id, template.id)
        self.assertEqual(retrieved_template.name, "Test Template")

        # Test getting by ID without version (should get the template)
        latest_template = HogFunctionTemplate.get_template("test-template")
        self.assertEqual(latest_template.id, template.id)

        # Test getting a non-existent template
        nonexistent_template = HogFunctionTemplate.get_template("non-existent-template")
        self.assertIsNone(nonexistent_template)

    def test_update_existing_template(self):
        """Test updating an existing template with new content"""
        from posthog.cdp.templates.hog_function_template import HogFunctionTemplate as HogFunctionTemplateDTO

        # First create a simple template
        original_dto = HogFunctionTemplateDTO(
            id="update-test",
            name="Original Template",
            hog="return event",
            inputs_schema={"field": "value"},
            status="alpha",
            type="destination",
            free=True,
            category=["Testing"],
        )

        # Create the template in the database
        original_template, created = HogFunctionTemplate.create_from_dataclass(original_dto)
        self.assertTrue(created, "Template should be created")
        original_version = original_template.version

        # Now create an updated version of the same template
        updated_dto = HogFunctionTemplateDTO(
            id="update-test",  # Same ID
            name="Updated Template",  # Changed
            hog="return {...event, updated: true}",  # Changed
            inputs_schema={"field": "value", "new_field": "new_value"},  # Changed
            status="beta",  # Changed
            type="destination",
            free=True,
            category=["Testing", "Updated"],  # Changed
        )

        # Update the template
        updated_template, created = HogFunctionTemplate.create_from_dataclass(updated_dto)
        self.assertFalse(created, "Template should be updated, not created")
        self.assertNotEqual(updated_template.version, original_version, "Version should change when content changes")

        # Verify the template was updated
        self.assertEqual(updated_template.template_id, "update-test")
        self.assertEqual(updated_template.name, "Updated Template")
        self.assertEqual(updated_template.status, "beta")
        self.assertEqual(updated_template.category, ["Testing", "Updated"])

        # Check database to ensure only one template exists with this ID
        templates = HogFunctionTemplate.objects.filter(template_id="update-test")
        self.assertEqual(templates.count(), 1, "Only one template should exist with this ID")

        # Now updating with the same content shouldn't change the version
        same_updated_template, created = HogFunctionTemplate.create_from_dataclass(updated_dto)
        self.assertFalse(created, "Template should not be re-created")
        self.assertEqual(
            same_updated_template.version,
            updated_template.version,
            "Version should not change when content is the same",
        )

    def test_get_latest_templates(self):
        """Test the get_latest_templates method with various filters and options"""
        # Create templates with various statuses
        self._create_template(
            template_id="active-template",
            version="1.0.0",
            name="Active Template",
            status="stable",
        )

        self._create_template(
            template_id="deprecated-template",
            version="1.0.0",
            name="Deprecated Template",
            status="deprecated",
        )

        # Create templates with different types
        self._create_template(
            template_id="template-a",
            version="1.0.0",
            name="Template A",
            status="alpha",
        )

        self._create_template(
            template_id="template-b",
            version="1.0.0",
            name="Template B",
            status="beta",
        )

        # Create a different type template
        self._create_template(
            template_id="template-c",
            version="1.0.0",
            name="Template C",
            type="transformation",
            status="stable",
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

    def test_versioning(self):
        """Test template versioning system including status and related fields"""
        from posthog.cdp.templates.hog_function_template import (
            HogFunctionTemplate as HogFunctionTemplateDTO,
            HogFunctionMapping,
            HogFunctionSubTemplate,
            HogFunctionMappingTemplate,
        )

        # Test 1: Basic version generation
        # Test empty content
        empty_version = HogFunctionTemplate.generate_version_from_content("")
        self.assertEqual(len(empty_version), 8)

        # Test identical content produces identical versions
        content1 = "return event"
        content2 = "return event"

        version1 = HogFunctionTemplate.generate_version_from_content(content1)
        version2 = HogFunctionTemplate.generate_version_from_content(content2)

        self.assertEqual(version1, version2)

        # Test different content produces different versions
        content3 = "return modified_event"
        version3 = HogFunctionTemplate.generate_version_from_content(content3)

        self.assertNotEqual(version1, version3)

        # Test 2: Status change creates new version
        template_alpha = HogFunctionTemplateDTO(
            id="test-status-template",
            name="Test Template",
            hog="return event",
            inputs_schema={},
            status="alpha",
            type="destination",
            free=True,
            category=[],
        )

        template_beta = HogFunctionTemplateDTO(
            id="test-status-template",
            name="Test Template",
            hog="return event",
            inputs_schema={},
            status="beta",
            type="destination",
            free=True,
            category=[],
        )

        # Create first version
        db_template_alpha, created_alpha = HogFunctionTemplate.create_from_dataclass(template_alpha)
        self.assertTrue(created_alpha)

        # Update with new status - should change version but not create new record
        db_template_beta, created_beta = HogFunctionTemplate.create_from_dataclass(template_beta)
        self.assertFalse(created_beta)
        self.assertNotEqual(db_template_alpha.version, db_template_beta.version)

        # Verify only one template exists
        templates = HogFunctionTemplate.objects.filter(template_id="test-status-template")
        self.assertEqual(templates.count(), 1)

        # Test 3: Changes to related fields create new versions
        base_template = HogFunctionTemplateDTO(
            id="advanced-template",
            name="Advanced Template",
            hog="return event",
            inputs_schema={},
            status="stable",
            type="destination",
            free=True,
            category=[],
        )

        # Create template with mappings
        template_with_mappings = HogFunctionTemplateDTO(
            id="advanced-template",
            name="Advanced Template",
            hog="return event",
            inputs_schema={},
            status="stable",
            type="destination",
            free=True,
            category=[],
            mappings=[HogFunctionMapping(filters={"event": "$pageview"})],
        )

        # Create base template first
        db_base, created_base = HogFunctionTemplate.create_from_dataclass(base_template)
        self.assertTrue(created_base)

        # Update with mappings
        db_mappings, created_mappings = HogFunctionTemplate.create_from_dataclass(template_with_mappings)
        self.assertFalse(created_mappings)
        self.assertNotEqual(db_base.version, db_mappings.version, "Adding mappings should change version")

        # Verify only one template exists with this ID
        templates = HogFunctionTemplate.objects.filter(template_id="advanced-template")
        self.assertEqual(templates.count(), 1)

        # Create template with sub_templates
        template_with_subtemplates = HogFunctionTemplateDTO(
            id="advanced-template",
            name="Advanced Template",
            hog="return event",
            inputs_schema={},
            status="stable",
            type="destination",
            free=True,
            category=[],
            sub_templates=[HogFunctionSubTemplate(id="sub1", name="Sub Template 1")],
        )

        # Update with sub-templates
        db_subtemplates, created_subtemplates = HogFunctionTemplate.create_from_dataclass(template_with_subtemplates)
        self.assertFalse(created_subtemplates)
        self.assertNotEqual(db_mappings.version, db_subtemplates.version, "Adding sub_templates should change version")

        # Create template with filters
        template_with_filters = HogFunctionTemplateDTO(
            id="advanced-template",
            name="Advanced Template",
            hog="return event",
            inputs_schema={},
            status="stable",
            type="destination",
            free=True,
            category=[],
            filters={"events": [{"id": "$pageview"}]},
        )

        # Update with filters
        db_filters, created_filters = HogFunctionTemplate.create_from_dataclass(template_with_filters)
        self.assertFalse(created_filters)
        self.assertNotEqual(db_subtemplates.version, db_filters.version, "Adding filters should change version")

        # Create template with mapping_templates
        template_with_mapping_templates = HogFunctionTemplateDTO(
            id="advanced-template",
            name="Advanced Template",
            hog="return event",
            inputs_schema={},
            status="stable",
            type="destination",
            free=True,
            category=[],
            mapping_templates=[HogFunctionMappingTemplate(name="Mapping Template 1")],
        )

        # Update with mapping templates
        db_mapping_templates, created_mapping_templates = HogFunctionTemplate.create_from_dataclass(
            template_with_mapping_templates
        )
        self.assertFalse(created_mapping_templates)
        self.assertNotEqual(
            db_filters.version, db_mapping_templates.version, "Adding mapping_templates should change version"
        )

        # Check total template count remains at 1
        templates = HogFunctionTemplate.objects.filter(template_id="advanced-template")
        self.assertEqual(templates.count(), 1, "Only one template should exist with this ID despite multiple updates")

    def test_dataclass_conversion_roundtrip(self):
        """Test converting between database model and dataclass representation"""
        from posthog.cdp.templates.hog_function_template import (
            HogFunctionMapping,
            HogFunctionSubTemplate,
        )

        # Create a complex template with mappings and sub-templates
        template = HogFunctionTemplate.objects.create(
            template_id="complex-template",
            version="1.0.0",
            name="Complex Template",
            description="Template with sub-templates and mappings",
            hog="return event",
            inputs_schema={"key": "value"},
            type="destination",
            status="stable",
            category=["Integration", "Analytics"],
            free=True,
            sub_templates=[{"id": "sub1", "name": "Sub Template 1", "description": "First sub-template"}],
            mappings=[{"filters": {"event": "$pageview"}, "inputs": {"message": "Page viewed"}}],
        )

        # Convert to dataclass
        dataclass_template = template.to_dataclass()

        # Verify fields were converted correctly
        self.assertEqual(dataclass_template.id, "complex-template")
        self.assertEqual(dataclass_template.name, "Complex Template")
        self.assertEqual(dataclass_template.description, "Template with sub-templates and mappings")
        self.assertEqual(dataclass_template.inputs_schema, {"key": "value"})
        self.assertEqual(dataclass_template.category, ["Integration", "Analytics"])
        self.assertEqual(dataclass_template.free, True)

        # Verify sub-templates were converted to proper objects
        self.assertEqual(len(dataclass_template.sub_templates), 1)
        self.assertIsInstance(dataclass_template.sub_templates[0], HogFunctionSubTemplate)
        self.assertEqual(dataclass_template.sub_templates[0].id, "sub1")

        # Verify mappings were converted to proper objects
        self.assertEqual(len(dataclass_template.mappings), 1)
        self.assertIsInstance(dataclass_template.mappings[0], HogFunctionMapping)
        self.assertEqual(dataclass_template.mappings[0].filters, {"event": "$pageview"})
        self.assertEqual(dataclass_template.mappings[0].inputs, {"message": "Page viewed"})

        # Convert back to database model
        new_template, _ = HogFunctionTemplate.create_from_dataclass(dataclass_template)

        # Verify fields were preserved through the roundtrip
        self.assertEqual(new_template.template_id, template.template_id)
        self.assertEqual(new_template.name, template.name)
        self.assertEqual(new_template.description, template.description)
        self.assertEqual(new_template.type, template.type)
        self.assertEqual(new_template.category, template.category)

        # Verify sub-templates were preserved
        self.assertEqual(len(new_template.sub_templates), 1)
        self.assertEqual(new_template.sub_templates[0]["id"], "sub1")

        # Verify mappings were preserved
        self.assertEqual(len(new_template.mappings), 1)
        self.assertEqual(new_template.mappings[0]["filters"], {"event": "$pageview"})
        self.assertEqual(new_template.mappings[0]["inputs"], {"message": "Page viewed"})

    def test_sync_template_idempotency(self):
        """Test that syncing the same template multiple times works correctly"""
        from posthog.cdp.templates.hog_function_template import HogFunctionTemplate as HogFunctionTemplateDTO
        import threading
        import queue

        # Create a simple test template DTO
        template_dto = HogFunctionTemplateDTO(
            id="sync-test-template",
            name="Sync Test Template",
            hog="return event",
            inputs_schema={"key": "value"},
            status="stable",
            type="destination",
            free=True,
            category=[],
        )

        # First, create the template directly to make sure it works
        initial_template, _ = HogFunctionTemplate.create_from_dataclass(template_dto)
        self.assertIsNotNone(initial_template)

        # Verify the template was saved
        initial_count = HogFunctionTemplate.objects.filter(template_id="sync-test-template").count()
        self.assertEqual(initial_count, 1, "Template should be created successfully before threading test")

        # Create 5 threads that all try to create the same template at the same time
        results = queue.Queue()

        def create_template():
            try:
                template, _ = HogFunctionTemplate.create_from_dataclass(template_dto)
                template_id = str(template.id)
                # Check immediately if our template is found
                count = HogFunctionTemplate.objects.filter(id=template.id).count()
                results.put(f"{template_id}:{count}")
            except Exception as e:
                results.put(f"Error: {str(e)}")

        threads = []
        for _ in range(5):
            thread = threading.Thread(target=create_template)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All threads should successfully complete
        result_ids = []
        thread_counts = []
        for _ in range(5):
            if not results.empty():
                result = results.get()
                if result.startswith("Error:"):
                    self.fail(f"Thread had error: {result}")
                else:
                    parts = result.split(":")
                    result_ids.append(parts[0])
                    thread_counts.append(int(parts[1]))

        # All results should be valid IDs (no errors)
        self.assertEqual(len(result_ids), 5)

        # All results should point to the same template
        self.assertEqual(len(set(result_ids)), 1, "All results should reference the same template ID")

        # All threads should see their template in the database
        for count in thread_counts:
            self.assertEqual(count, 1, "Each thread should be able to see its template")

        # Check there's only one template with this ID in the database
        # Use a separate transaction to ensure we see the latest database state
        from django.db import transaction

        with transaction.atomic():
            templates = HogFunctionTemplate.objects.filter(template_id="sync-test-template")
            final_count = templates.count()

        self.assertEqual(final_count, 1, f"Should have exactly one template, got {final_count}")

        # Creating the same template again should not add a duplicate
        HogFunctionTemplate.create_from_dataclass(template_dto)
        templates = HogFunctionTemplate.objects.filter(template_id="sync-test-template")
        self.assertEqual(templates.count(), 1)
