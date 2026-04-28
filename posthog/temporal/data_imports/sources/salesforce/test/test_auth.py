import json

import pytest
import unittest.mock

import requests

from posthog.temporal.data_imports.sources.salesforce import auth


def test_salesforce_refresh_access_token_raises_on_client_failure():
    """Test whether an exception is raised when failing with a client error."""
    status_code = 400
    error_description = "Bad client!"

    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps({"error_description": error_description}).encode("utf-8")

    with (
        unittest.mock.patch(
            "posthog.temporal.data_imports.sources.salesforce.auth.requests.post", return_value=response
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Client Error" in str(exc.value)
    assert error_description in str(exc.value)


def test_salesforce_refresh_access_token_raises_on_server_failure():
    """Test whether an exception is raised when failing with a server error."""
    status_code = 500
    response_body = "something went terribly wrong"

    response = requests.Response()
    response.status_code = status_code
    response._content = response_body.encode("utf-8")

    with (
        unittest.mock.patch(
            "posthog.temporal.data_imports.sources.salesforce.auth.requests.post", return_value=response
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.salesforce_refresh_access_token("something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Server Error" in str(exc.value)
    assert response_body in str(exc.value)


def test_get_salesforce_access_token_from_code_raises_on_client_failure():
    """Test whether an exception is raised when failing with a client error."""
    status_code = 400
    error_description = "Bad client!"

    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps({"error_description": error_description}).encode("utf-8")

    with (
        unittest.mock.patch(
            "posthog.temporal.data_imports.sources.salesforce.auth.requests.post", return_value=response
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.get_salesforce_access_token_from_code("something", "something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Client Error" in str(exc.value)
    assert error_description in str(exc.value)


def test_get_salesforce_access_token_from_code_raises_on_server_failure():
    """Test whether an exception is raised when failing with a server error."""
    status_code = 500
    response_body = "something went terribly wrong"

    response = requests.Response()
    response.status_code = status_code
    response._content = response_body.encode("utf-8")

    with (
        unittest.mock.patch(
            "posthog.temporal.data_imports.sources.salesforce.auth.requests.post", return_value=response
        ),
        pytest.raises(auth.SalesforceAuthRequestError) as exc,
    ):
        _ = auth.get_salesforce_access_token_from_code("something", "something", "https://login.salesforce.com")

    assert exc.value.response == response
    assert "Server Error" in str(exc.value)
    assert response_body in str(exc.value)
