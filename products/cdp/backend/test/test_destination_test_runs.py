from django.test import SimpleTestCase

from products.cdp.backend.services.destination_test_runs import destination_test_run_context


class TestDestinationTestRunContext(SimpleTestCase):
    def test_mapping_input_that_replaces_an_integration_input_records_the_replacement(self) -> None:
        configuration = {
            "hog": "return event",
            "inputs_schema": [{"key": "account", "type": "integration", "integration": "slack"}],
            "inputs": {"account": {"value": 5}},
            "mappings": [
                {
                    "inputs_schema": [{"key": "account", "type": "number"}],
                    "inputs": {"account": {"value": 9}},
                }
            ],
        }

        context = destination_test_run_context(configuration, stored=None, mock_async_functions=False)

        assert context.integration_ids == [9]
