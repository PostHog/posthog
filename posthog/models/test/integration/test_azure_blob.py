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


@pytest.mark.parametrize(
    "reason,expected_error",
    [
        ("Disallowed target IP: 10.0.0.1", EndpointNotAllowedError),
        (HOST_RESOLUTION_FAILED_REASON, EndpointResolutionError),
    ],
)
@override_settings(FORCE_URL_VALIDATION=True)
def test_rejected_endpoint_reports_the_host_and_the_reason(reason: str, expected_error: type[ValueError]) -> None:
    with patch("posthog.models.integration.azure_blob.is_url_allowed", return_value=(False, reason)):
        with pytest.raises(expected_error) as exc_info:
            validate_azure_blob_connection_string(CONNECTION_STRING)

    assert "name.blob.example.com" in str(exc_info.value)


@override_settings(FORCE_URL_VALIDATION=True)
def test_rejected_endpoint_message_leaves_out_any_userinfo() -> None:
    connection_string = (
        "DefaultEndpointsProtocol=https;AccountName=name;AccountKey=key;"
        "BlobEndpoint=https://user:token@name.blob.example.com;"
    )
    with patch("posthog.models.integration.azure_blob.is_url_allowed", return_value=(False, "a reason")):
        with pytest.raises(EndpointNotAllowedError) as exc_info:
            validate_azure_blob_connection_string(connection_string)

    assert "token" not in str(exc_info.value)
