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
            (
                "non_ascii_secret_inside_a_longer_label",
                "Bücher-Geheimnis",
                "https://xn--xbcher-geheimnis-kzb.example.com",
                "https://***REDACTED***.example.com",
            ),
            ("short_secret_inside_a_longer_label", "eu", "https://europe.example.com", "https://europe.example.com"),
            (
                "short_secret_that_fills_a_label",
                "s3cret7",
                "https://s3cret7.example.com",
                "https://***REDACTED***.example.com",
            ),
            (
                "secret_that_uts46_keeps_and_idna2003_maps",
                "paßwörter",
                "https://xn--pawrter-1va2s.example.com",
                "https://***REDACTED***.example.com",
            ),
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
            (
                "secret_that_names_a_tenant_on_a_shared_host",
                "fake-host-secret",
                "https://fake-host-secret.workers.dev",
                "https://***REDACTED***.workers.dev",
            ),
            (
                "secret_in_a_host_without_a_public_suffix",
                "fake-host-secret",
                "https://fake-host-secret.svc.internal",
                "https://***REDACTED***.svc.internal",
            ),
        ]
    )
    def test_redacts_a_stored_secret_in_the_form_a_url_parser_writes_the_host(
        self, _name: str, secret: str, origin: str, expected: str
    ) -> None:
        assert redact_secrets_in_origins([origin], [secret]) == [expected]
