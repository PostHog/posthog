"""
Custom exceptions for REST API sources.
"""


class RestApiException(Exception):
    """Base exception for REST API errors."""

    pass


class IgnoreResponseException(RestApiException):
    """Exception raised to ignore a response (used in response action hooks)."""

    pass
