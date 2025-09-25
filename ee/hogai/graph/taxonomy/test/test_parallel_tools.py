from datetime import datetime

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import (
    ActorsPropertyTaxonomyResponse,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyItem,
)

from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit


class TestTaxonomyToolkit(BaseTest):
    def setUp(self):
        self.toolkit = TaxonomyAgentToolkit(self.team)

    def _create_mock_taxonomy_response(self, response_type="event", results=None, **kwargs):
        """Helper to create mock taxonomy responses"""
        if results is None:
            # Create single result from kwargs
            if response_type == "event":
                results = [EventTaxonomyItem(**kwargs)]
            elif response_type == "actors":
                results = [ActorsPropertyTaxonomyResponse(**kwargs)]

        if response_type == "event":
            return CachedEventTaxonomyQueryResponse(
                cache_key="test",
                is_cached=False,
                last_refresh=datetime.now().isoformat(),
                next_allowed_client_refresh=datetime.now().isoformat(),
                timezone="UTC",
                results=results,
            )
        elif response_type == "actors":
            return CachedActorsPropertyTaxonomyQueryResponse(
                cache_key="test",
                is_cached=False,
                last_refresh=datetime.now().isoformat(),
                next_allowed_client_refresh=datetime.now().isoformat(),
                timezone="UTC",
                results=results,
            )

    # Entities

    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    def test_retrieve_entity_properties_person(self, mock_property_definition):
        mock_property_definition.objects.filter.return_value.values_list.return_value = [
            ("email", "String"),
            ("name", "String"),
        ]

        result = self.toolkit.retrieve_entity_properties("person")
        self.assertIn("email", result)
        self.assertIn("String", result)

    @patch("ee.hogai.graph.taxonomy.toolkit.ActorsPropertyTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_entity_property_values_person(
        self, mock_group_mapping, mock_property_definition, mock_runner_class
    ):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        mock_prop = Mock()
        mock_prop.name = "email"
        mock_prop.property_type = "String"
        mock_property_definition.objects.filter.return_value = [mock_prop]

        mock_response = self._create_mock_taxonomy_response(
            response_type="actors", sample_values=["test@example.com", "user@test.com"], sample_count=2
        )

        mock_runner = Mock()
        mock_runner.run.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_entity_property_values({"person": ["email"]})
        self.assertIn("test@example.com", result["person"][0])

    @patch("ee.hogai.graph.taxonomy.toolkit.ActorsPropertyTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_entity_property_values_person_multiple(
        self, mock_group_mapping, mock_property_definition, mock_runner_class
    ):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        mock_prop_email = Mock()
        mock_prop_email.name = "email"
        mock_prop_email.property_type = "String"
        mock_prop_name = Mock()
        mock_prop_name.name = "name"
        mock_prop_name.property_type = "String"
        mock_property_definition.objects.filter.return_value = [mock_prop_email, mock_prop_name]

        mock_result1 = ActorsPropertyTaxonomyResponse(
            sample_count=3, sample_values=["another@example.com", "user@test.com", "test@example.com"]
        )
        mock_result2 = ActorsPropertyTaxonomyResponse(
            sample_count=3, sample_values=["Bob Johnson", "Jane Smith", "John Doe"]
        )

        mock_cached_response = self._create_mock_taxonomy_response("actors", results=[mock_result1, mock_result2])
        mock_runner = Mock()
        mock_runner.run.return_value = mock_cached_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_entity_property_values({"person": ["email", "name"]})
        result_str = "\n".join(result["person"]) if isinstance(result, dict) else result
        self.assertIn("property: email", result_str)
        self.assertIn("another@example.com", result_str)
        self.assertIn("user@test.com", result_str)
        self.assertIn("test@example.com", result_str)

        self.assertIn("property: name", result_str)
        self.assertIn("Bob Johnson", result_str)
        self.assertIn("Jane Smith", result_str)
        self.assertIn("John Doe", result_str)

    @patch("ee.hogai.graph.taxonomy.toolkit.ActorsPropertyTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_entity_property_values_person_no_results(
        self, mock_group_mapping, mock_property_definition, mock_runner_class
    ):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        mock_prop_email = Mock()
        mock_prop_email.name = "email"
        mock_prop_email.property_type = "String"
        mock_property_definition.objects.filter.return_value = [mock_prop_email]

        mock_prop_name = Mock()
        mock_prop_name.name = "name"
        mock_prop_name.property_type = "String"
        mock_property_definition.objects.filter.return_value = [mock_prop_name]

        mock_cached_response = self._create_mock_taxonomy_response("actors", results=[])
        mock_runner = Mock()
        mock_runner.run.return_value = mock_cached_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_entity_property_values({"person": ["email", "name"]})
        result_str = "\n".join(result["person"]) if isinstance(result, dict) else result
        self.assertIn("No values found for property email on entity person", result_str)
        self.assertIn("No values found for property name on entity person", result_str)

    @patch("ee.hogai.graph.taxonomy.toolkit.ActorsPropertyTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_entity_property_no_values_multiple(
        self, mock_group_mapping, mock_property_definition, mock_runner_class
    ):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        mock_prop_address = Mock()
        mock_prop_address.name = "address"
        mock_prop_address.property_type = "String"

        mock_prop_name = Mock()
        mock_prop_name.name = "name"
        mock_prop_name.property_type = "String"

        mock_prop_city = Mock()
        mock_prop_city.name = "city"
        mock_prop_city.property_type = "String"

        mock_prop_age = Mock()
        mock_prop_age.name = "age"
        mock_prop_age.property_type = "Numeric"
        mock_property_definition.objects.filter.return_value = [
            mock_prop_name,
            mock_prop_address,
            mock_prop_city,
            mock_prop_age,
        ]

        mock_result = ActorsPropertyTaxonomyResponse(sample_count=0, sample_values=[])
        mock_result2 = ActorsPropertyTaxonomyResponse(
            sample_count=3, sample_values=["Bob Johnson", "Jane Smith", "John Doe"]
        )
        mock_result3 = ActorsPropertyTaxonomyResponse(
            sample_count=10, sample_values=["New York", "Los Angeles", "Chicago"]
        )

        mock_cached_response = self._create_mock_taxonomy_response(
            "actors", results=[mock_result, mock_result2, mock_result3]
        )
        mock_runner = Mock()
        mock_runner.run.return_value = mock_cached_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_entity_property_values({"person": ["address"]})
        result_str = "\n".join(result["person"]) if isinstance(result, dict) else result
        self.assertIn("The property does not have any values in the taxonomy.", result_str)

        result = self.toolkit.retrieve_entity_property_values({"person": ["address", "name"]})
        result_str = "\n".join(result["person"]) if isinstance(result, dict) else result
        self.assertIn("The property does not have any values in the taxonomy.", result_str)
        self.assertIn("property: name", result_str)
        self.assertIn("Bob Johnson", result_str)
        self.assertIn("Jane Smith", result_str)
        self.assertIn("John Doe", result_str)

        result = self.toolkit.retrieve_entity_property_values({"person": ["address", "name", "city"]})
        result_str = "\n".join(result["person"]) if isinstance(result, dict) else result
        self.assertIn("and 7 more distinct values", result_str)

    @patch("ee.hogai.graph.taxonomy.toolkit.ActorsPropertyTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_entity_property_different_value_types_multiple(
        self, mock_group_mapping, mock_property_definition, mock_runner_class
    ):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        mock_prop_name = Mock()
        mock_prop_name.name = "name"
        mock_prop_name.property_type = "String"
        mock_prop_age = Mock()
        mock_prop_age.name = "age"
        mock_prop_age.property_type = "Numeric"
        mock_property_definition.objects.filter.return_value = [mock_prop_name, mock_prop_age]

        mock_result = ActorsPropertyTaxonomyResponse(
            sample_count=3, sample_values=["Bob Johnson", "Jane Smith", "John Doe"]
        )
        mock_result2 = ActorsPropertyTaxonomyResponse(sample_count=3, sample_values=[25, 30, 35])

        # Create a single CachedActorsPropertyTaxonomyQueryResponse with a list of result dicts
        mock_cached_response = self._create_mock_taxonomy_response("actors", results=[mock_result, mock_result2])
        mock_runner = Mock()
        mock_runner.run.return_value = mock_cached_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_entity_property_values({"person": ["name", "age"]})
        result_str = "\n".join(result["person"]) if isinstance(result, dict) else result
        self.assertIn("property: name", result_str)
        self.assertIn("Bob Johnson", result_str)
        self.assertIn("Jane Smith", result_str)
        self.assertIn("John Doe", result_str)
        self.assertIn("property: age", result_str)
        self.assertIn("25", result_str)
        self.assertIn("30", result_str)
        self.assertIn("35", result_str)

    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_entity_property_values_invalid_entity(self, mock_group_mapping, mock_property_definition):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        result = self.toolkit.retrieve_entity_property_values({"invalid": ["prop"]})
        self.assertIn("Entity invalid not found", result["invalid"][0])

    @patch("ee.hogai.graph.taxonomy.toolkit.ActorsPropertyTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_group_property_values(self, mock_group_mapping, mock_property_definition, mock_runner_class):
        # Create a mock group object
        mock_group = Mock()
        mock_group.group_type = "group"
        mock_group.group_type_index = 0
        mock_group_mapping.objects.filter.return_value.order_by.return_value = [mock_group]

        mock_prop = Mock()
        mock_prop.name = "prop"
        mock_prop.property_type = "String"
        mock_property_definition.objects.filter.return_value = [mock_prop]

        mock_cached_response = self._create_mock_taxonomy_response(
            "actors",
            results=[
                ActorsPropertyTaxonomyResponse(
                    sample_count=3,
                    sample_values=[
                        "value1",
                    ],
                )
            ],
        )
        mock_runner = Mock()
        mock_runner.run.return_value = mock_cached_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_entity_property_values({"group": ["prop"]})
        result_str = "\n".join(result["group"]) if isinstance(result, dict) else result
        self.assertIn("value1", result_str)

    @parameterized.expand(
        [
            ("$session_duration", True, "'30'\n- '146'\n- '2'\n- and many more distinct values"),
            ("$channel_type", True, "Direct"),
            ("nonexistent_property", False, "does not exist"),
        ]
    )
    def test_retrieve_session_properties(self, property_name, should_contain_values, expected_content):
        result = self.toolkit._retrieve_session_properties(property_name)
        if should_contain_values:
            self.assertIn(expected_content, result)
        else:
            self.assertIn(expected_content, result)

    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_session_properties_values(self, mock_group_mapping):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []
        result = self.toolkit.retrieve_entity_property_values({"session": ["$session_duration"]})
        result_str = "\n".join(result["session"]) if isinstance(result, dict) else result

        self.assertIn("30", result_str)
        self.assertIn("146", result_str)
        self.assertIn("2", result_str)
        self.assertIn("and many more distinct values", result_str)

    def test_retrieve_entity_property_values_batching(self):
        """Test that when more than 6 entities are processed, they are sent in batches of 6"""
        # Create 8 entities (more than 6) to test batching
        entities = [f"entity_{i}" for i in range(8)]
        entity_properties = {entity: ["email"] for entity in entities}

        # Spy on the _handle_entity_batch method to track how many times it's called
        with patch.object(self.toolkit, "_handle_entity_batch") as mock_handle_batch:
            # Mock the method to return a simple result
            mock_handle_batch.return_value = {entity: ["test@example.com"] for entity in entities}

            # Call the async method directly
            import asyncio

            result = asyncio.run(self.toolkit._parallel_entity_processing(entity_properties, entities, []))

            # Verify that we got results for all entities
            self.assertEqual(len(result), 8)
            for entity in entities:
                self.assertIn(entity, result)
                self.assertEqual(result[entity], ["test@example.com"])

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

    # Events and actions

    @patch("ee.hogai.graph.taxonomy.toolkit.EventTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_event_or_action_properties(self, mock_group_mapping, mock_property_definition, mock_runner_class):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        mock_prop = Mock()
        mock_prop.name = "$browser"
        mock_prop.property_type = "String"
        mock_property_definition.objects.filter.return_value = [mock_prop]

        mock_response = self._create_mock_taxonomy_response(property="$browser", sample_values=[], sample_count=0)

        mock_runner = Mock()
        mock_runner.run.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_event_or_action_properties("test_event")
        self.assertIn("$browser", result)

    def _get_mock_property_definition(self):
        mock_prop_browser = Mock()
        mock_prop_browser.name = "$browser"
        mock_prop_browser.property_type = "String"
        mock_prop_device_type = Mock()
        mock_prop_device_type.name = "$device_type"
        mock_prop_device_type.property_type = "String"
        return [mock_prop_browser, mock_prop_device_type]

    @patch("ee.hogai.graph.taxonomy.toolkit.EventTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    def test_retrieve_event_or_action_property_values(self, mock_property_definition, mock_runner_class):
        mock_property_definition.objects.filter.return_value = self._get_mock_property_definition()

        mock_response = self._create_mock_taxonomy_response(
            property="$browser", sample_values=["Chrome", "Firefox"], sample_count=2
        )

        mock_runner = Mock()
        mock_runner.run.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_event_or_action_property_values({"test_event": ["$browser"]})["test_event"][0]
        self.assertIn("Chrome", result)
        self.assertIn("Firefox", result)
        self.assertIn("property: $browser", result)
        self.assertNotIn("property: $device_type", result)

    @patch("ee.hogai.graph.taxonomy.toolkit.EventTaxonomyQueryRunner")
    @patch("ee.hogai.graph.taxonomy.toolkit.PropertyDefinition")
    @patch("ee.hogai.graph.taxonomy.toolkit.GroupTypeMapping")
    def test_retrieve_event_or_action_property_values_multiple(
        self, mock_group_mapping, mock_property_definition, mock_runner_class
    ):
        mock_group_mapping.objects.filter.return_value.order_by.return_value = []

        mock_property_definition.objects.filter.return_value = self._get_mock_property_definition()

        mock_response = EventTaxonomyItem(property="$browser", sample_values=["Chrome", "Firefox"], sample_count=2)
        mock_response2 = EventTaxonomyItem(property="$device_type", sample_values=["Mobile", "Desktop"], sample_count=2)

        mock_cached_response = self._create_mock_taxonomy_response("event", results=[mock_response, mock_response2])
        mock_runner = Mock()
        mock_runner.run.return_value = mock_cached_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_event_or_action_property_values(
            {"test_event": ["$browser", "$device_type", "does_not_exist"]}
        )
        result_str = "\n".join(result["test_event"]) if isinstance(result, dict) else result
        self.assertIn("Chrome", result_str)
        self.assertIn("Firefox", result_str)
        self.assertIn("property: $browser", result_str)
        self.assertIn(
            "The property does_not_exist does not exist in the taxonomy for entity event test_event", result_str
        )
