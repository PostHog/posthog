from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.services.destination_test_runs import destination_test_run_context, redact_secrets_in_origins


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

    @parameterized.expand(
        [
            (
                "secret_in_another_case",
                "Fake-Host-Secret",
                "https://fake-host-secret.example.com",
                "https://***REDACTED***.example.com",
            ),
            (
                "non_ascii_secret_in_punycode",
                "bücher-geheimnis",
                "https://xn--bcher-geheimnis-zvb.example.com",
                "https://***REDACTED***.example.com",
            ),
            ("secret_too_short_to_be_a_credential", "eu", "https://eu.example.com", "https://eu.example.com"),
            (
                "secret_that_names_the_registrable_domain",
                "evil-attacker.com",
                "https://evil-attacker.com",
                "https://evil-attacker.com",
            ),
            (
                "secret_in_the_domain_under_a_subdomain",
                "fake-host-secret",
                "https://api.fake-host-secret.com:8443",
                "https://api.fake-host-secret.com:8443",
            ),
        ]
    )
    def test_redacts_a_stored_secret_in_the_form_a_url_parser_writes_the_host(
        self, _name: str, secret: str, origin: str, expected: str
    ) -> None:
        assert redact_secrets_in_origins([origin], [secret]) == [expected]
