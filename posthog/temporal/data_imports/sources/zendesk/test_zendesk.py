from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.generated_configs import ZendeskSourceConfig
from posthog.temporal.data_imports.sources.zendesk.source import ZendeskSource
from posthog.temporal.data_imports.sources.zendesk.zendesk import (
    normalize_subdomain,
    validate_credentials,
    zendesk_source,
)


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("plain_label", "acme", "acme"),
            ("full_host", "acme.zendesk.com", "acme"),
            ("full_host_uppercase", "ACME.ZENDESK.COM", "ACME"),
            ("https_url", "https://acme.zendesk.com", "acme"),
            ("https_url_trailing_slash", "https://acme.zendesk.com/", "acme"),
            ("http_url", "http://acme.zendesk.com/", "acme"),
            ("scheme_uppercase", "HTTPS://acme.zendesk.com", "acme"),
            ("url_with_path", "https://acme.zendesk.com/agent/dashboard", "acme"),
            ("host_with_path", "acme.zendesk.com/agent", "acme"),
            ("whitespace", "  acme.zendesk.com  ", "acme"),
            ("hyphenated_label", "my-team.zendesk.com", "my-team"),
        ]
    )
    def test_normalize(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected


class TestZendeskSourceURLConstruction:
    @patch("posthog.temporal.data_imports.sources.zendesk.zendesk.rest_api_resource")
    def test_zendesk_source_normalizes_full_hostname(self, mock_rest_api_resource: Mock) -> None:
        mock_rest_api_resource.return_value = Mock()

        zendesk_source(
            subdomain="nibbles.zendesk.com",
            api_key="key",
            email_address="user@example.com",
            endpoint="tickets",
            team_id=1,
            job_id="job",
            db_incremental_field_last_value=None,
        )

        config_arg = mock_rest_api_resource.call_args[0][0]
        assert config_arg["client"]["base_url"] == "https://nibbles.zendesk.com/"

    @patch("posthog.temporal.data_imports.sources.zendesk.zendesk.requests.get")
    def test_validate_credentials_normalizes_full_hostname(self, mock_get: Mock) -> None:
        mock_get.return_value = Mock(status_code=200)

        assert validate_credentials("nibbles.zendesk.com", "key", "user@example.com") is True

        called_url = mock_get.call_args[0][0]
        assert called_url == "https://nibbles.zendesk.com/api/v2/tickets/count"


class TestZendeskSourceValidateCredentials:
    @patch("posthog.temporal.data_imports.sources.zendesk.source.validate_credentials")
    def test_full_hostname_subdomain_passes_regex_after_normalize(self, mock_validate: Mock) -> None:
        mock_validate.return_value = True
        source = ZendeskSource()
        config = ZendeskSourceConfig(
            subdomain="nibbles.zendesk.com",
            api_key="key",
            email_address="user@example.com",
        )

        ok, err = source.validate_credentials(config, team_id=1)

        assert (ok, err) == (True, None)
        mock_validate.assert_called_once_with("nibbles", "key", "user@example.com")

    def test_invalid_subdomain_still_rejected(self) -> None:
        source = ZendeskSource()
        config = ZendeskSourceConfig(
            subdomain="bad subdomain!",
            api_key="key",
            email_address="user@example.com",
        )

        ok, err = source.validate_credentials(config, team_id=1)

        assert ok is False
        assert err == "Zendesk subdomain is incorrect"
