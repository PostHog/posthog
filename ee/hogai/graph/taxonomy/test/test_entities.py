from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from posthog.models.person import Person
from posthog.models.property_definition import PropertyDefinition
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit


class DummyToolkit(TaxonomyAgentToolkit):
    def get_tools(self):
        return self._get_default_tools()


class TestEntities(ClickhouseTestMixin, NonAtomicBaseTest):
    def setUp(self):
        super().setUp()
        for i, group_type in enumerate(["organization", "project"]):
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type_index=i, group_type=group_type
            )

        PropertyDefinition.objects.create(
            team=self.team,
            name="name",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.PERSON,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="name_group",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="property_no_values",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.PERSON,
        )

        Person.objects.create(
            team=self.team,
            distinct_ids=["test-user"],
            properties={"name": "Test User"},
        )

        self.toolkit = DummyToolkit(self.team, self.user)

    async def test_retrieve_entity_properties(self):
        result = await self.toolkit.retrieve_entity_properties_parallel(["person"])
        assert (
            "<properties><String><prop><name>name</name></prop><prop><name>property_no_values</name></prop></String></properties>"
            == result["person"]
        )

    async def test_retrieve_entity_properties_entity_not_found(self):
        result = await self.toolkit.retrieve_entity_properties_parallel(["test"])
        assert "Entity test not found. Available entities: person, session, organization, project" == result["test"]

    async def test_retrieve_entity_properties_entity_with_group(self):
        result = await self.toolkit.retrieve_entity_properties_parallel(["organization", "session"])
        assert "session" in result
        assert (
            "<properties><String><prop><name>name_group</name></prop></String></properties>" == result["organization"]
        )
        assert "<properties>" in result["session"]

    async def test_person_property_values_exists(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        self.assertEqual(result, expected)

        property_vals = await self.toolkit.retrieve_entity_property_values({"person": ["name"]})
        self.assertIn("person", property_vals)
        self.assertIn("name", "\n".join(property_vals.get("person", [])))
        self.assertTrue(any("Test User" in str(val) for val in property_vals.get("person", [])))

    async def test_person_property_values_do_not_exist(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        self.assertEqual(result, expected)

        property_vals = await self.toolkit.retrieve_entity_property_values({"person": ["property_no_values"]})
        self.assertIn("person", property_vals)
        self.assertIn("property_no_values", "\n".join(property_vals.get("person", [])))
        self.assertTrue(
            any(
                "The property does not have any values in the taxonomy." in str(val)
                for val in property_vals.get("person", [])
            )
        )

    async def test_person_property_values_mixed(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        self.assertEqual(result, expected)

        property_vals = await self.toolkit.retrieve_entity_property_values({"person": ["property_no_values", "name"]})

        self.assertIn("person", property_vals)
        self.assertIn("property_no_values", "\n".join(property_vals.get("person", [])))
        self.assertTrue(
            any(
                "The property does not have any values in the taxonomy." in str(val)
                for val in property_vals.get("person", [])
            )
        )
        self.assertIn("name", "\n".join(property_vals.get("person", [])))
        self.assertTrue(any("Test User" in str(val) for val in property_vals.get("person", [])))

    async def test_multiple_entities(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        self.assertEqual(result, expected)

        property_vals = await self.toolkit.retrieve_entity_property_values(
            {
                "person": ["property_no_values"],
                "session": ["$session_duration", "$channel_type", "nonexistent_property"],
            }
        )

        self.assertIn("person", property_vals)
        self.assertIn("property_no_values", "\n".join(property_vals.get("person", [])))
        self.assertTrue(
            any(
                "The property does not have any values in the taxonomy." in str(val)
                for val in property_vals.get("person", [])
            )
        )
        self.assertIn("session", property_vals)
        self.assertIn("$session_duration", "\n".join(property_vals.get("session", [])))
        self.assertIn("$channel_type", "\n".join(property_vals.get("session", [])))
        self.assertIn("nonexistent_property", "\n".join(property_vals.get("session", [])))
        self.assertTrue(
            any(
                "values:\n- '30'\n- '146'\n- '2'\n- and many more distinct values\n" in str(val)
                for val in property_vals.get("session", [])
            )
        )
        self.assertTrue(any("Direct" in str(val) for val in property_vals.get("session", [])))
        self.assertTrue(
            any(
                "The property nonexistent_property does not exist in the taxonomy." in str(val)
                for val in property_vals.get("session", [])
            )
        )

    async def test_retrieve_entity_property_values_batching(self):
        """Test that when more than 6 entities are processed, they are sent in batches of 6"""
        # Create 8 entities (more than 6) to test batching
        entities = [f"entity_{i}" for i in range(8)]
        entity_properties = {
            entity: ["$session_duration", "$channel_type", "nonexistent_property"] for entity in entities
        }

        # Spy on the _handle_entity_batch method to track how many times it's called
        with patch.object(self.toolkit, "_handle_entity_batch") as mock_handle_batch:
            # Mock the method to return a simple result
            mock_handle_batch.return_value = {
                entity: [
                    "values:\n- '30'\n- '146'\n- '2'\n- and many more distinct values\n",
                    "Direct",
                    "The property nonexistent_property does not exist in the taxonomy.",
                ]
                for entity in entities
            }

            result = await self.toolkit.retrieve_entity_property_values(entity_properties)

            # Verify that we got results for all entities
            self.assertEqual(len(result), 8)
            for entity in entities:
                self.assertIn(entity, result)
                self.assertEqual(
                    result[entity],
                    [
                        "values:\n- '30'\n- '146'\n- '2'\n- and many more distinct values\n",
                        "Direct",
                        "The property nonexistent_property does not exist in the taxonomy.",
                    ],
                )

            # Verify that _handle_entity_batch was called twice:
            # - First batch: entities 0-5 (6 entities)
            # - Second batch: entities 6-7 (2 entities)
            self.assertEqual(mock_handle_batch.call_count, 2)

            # Verify the batch sizes
            call_args_list = mock_handle_batch.call_args_list
            first_batch = call_args_list[0][0][0]  # First argument of first call
            second_batch = call_args_list[1][0][0]  # First argument of second call

            self.assertEqual(len(first_batch), 6)  # First batch should have 6 entities
            self.assertEqual(len(second_batch), 2)  # Second batch should have 2 entities
