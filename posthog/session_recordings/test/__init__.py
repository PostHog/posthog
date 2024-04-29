from unittest.mock import Mock


def setup_mock_requests_get(headers: dict | None = None) -> Mock:
    if headers is None:
        # some header that is not None, so we know that we're not passing all headers through unchanged
        headers = {"blah": "desired-value"}

    # Create a mock response object
    requests_get = Mock()

    # Setup status code and content if necessary
    requests_get.status_code = 200
    requests_get.content = b"Example content"

    # Setup headers and the .get method for headers
    requests_get.headers = headers

    # Mock the __enter__ and __exit__ methods to support the 'with' context
    requests_get.__enter__ = Mock(return_value=requests_get)
    requests_get.__exit__ = Mock(
        return_value=False
    )  # Normally handles exceptions, False means it does not suppress exceptions

    return requests_get
