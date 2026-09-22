import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.integration.azure_blob import (
    EndpointNotAllowedError,
    EndpointResolutionError,
    strip_leading_whitespace,
    validate_azure_blob_connection_string,
)
from posthog.security.url_validation import HOST_RESOLUTION_FAILED_REASON


@pytest.mark.parametrize(
    "conn_str,expected",
    [
        # No changes without leading whitespace
        ("AccountName=name;AccountKey=key;SomeKey=value", "AccountName=name;AccountKey=key;SomeKey=value"),
        # Stripped leading whitespace one time
        ("AccountName=name; AccountKey=key;SomeKey=value", "AccountName=name;AccountKey=key;SomeKey=value"),
        # Stripped leading whitespace two times
        ("AccountName=name; AccountKey=key; SomeKey=value", "AccountName=name;AccountKey=key;SomeKey=value"),
    ],
)
def test_strip_leading_whitespace(conn_str: str, expected: str) -> None:
    assert strip_leading_whitespace(conn_str) == expected


CONNECTION_STRING = (
    "DefaultEndpointsProtocol=https;AccountName=name;AccountKey=key;BlobEndpoint=https://name.blob.example.com;"
)


@override_settings(FORCE_URL_VALIDATION=True)
def test_blocked_endpoint_reports_the_endpoint_and_the_reason() -> None:
    with patch(
        "posthog.models.integration.azure_blob.is_url_allowed",
        return_value=(False, "Disallowed target IP: 10.0.0.1"),
    ):
        with pytest.raises(EndpointNotAllowedError) as exc_info:
            validate_azure_blob_connection_string(CONNECTION_STRING)

    assert "https://name.blob.example.com" in str(exc_info.value)
    assert "Disallowed target IP: 10.0.0.1" in str(exc_info.value)


@override_settings(FORCE_URL_VALIDATION=True)
def test_unresolvable_endpoint_is_reported_apart_from_a_block() -> None:
    with patch(
        "posthog.models.integration.azure_blob.is_url_allowed",
        return_value=(False, HOST_RESOLUTION_FAILED_REASON),
    ):
        with pytest.raises(EndpointResolutionError) as exc_info:
            validate_azure_blob_connection_string(CONNECTION_STRING)

    assert "https://name.blob.example.com" in str(exc_info.value)
