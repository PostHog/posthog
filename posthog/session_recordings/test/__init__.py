from unittest.mock import Mock


def setup_stream_from(headers: dict | None = None) -> Mock:
    if headers is None:
        # some header that is not None, so we know that we're not passing all headers through unchanged
        headers = {"blah": "desired-value"}

    # Create a mock response object
    streaming_interaction = Mock()

    # Setup status code and content if necessary
    streaming_interaction.status_code = 200
    streaming_interaction.content = b"Example content"
    streaming_interaction.raw = b"Example content"

    # Setup headers and the .get method for headers
    streaming_interaction.headers = headers

    # Mock the __enter__ and __exit__ methods to support the 'with' context
    streaming_interaction.__enter__ = Mock(return_value=streaming_interaction)
    streaming_interaction.__exit__ = Mock(
        return_value=False
    )  # Normally handles exceptions, False means it does not suppress exceptions

    return streaming_interaction
