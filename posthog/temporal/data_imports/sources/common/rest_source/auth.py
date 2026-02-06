"""
Authentication implementations for REST API sources.

Replaces DLT's authentication classes with simplified versions.
"""

import base64
from abc import ABC, abstractmethod

import requests


class AuthBase(ABC):
    """Base class for authentication.

    Compatible with dlt.sources.helpers.rest_client.auth.AuthConfigBase
    """

    @abstractmethod
    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        """Apply authentication to the request.

        Args:
            request: The prepared request to authenticate

        Returns:
            The authenticated request
        """
        pass


class BearerTokenAuth(AuthBase):
    """Bearer token authentication.

    Compatible with dlt.sources.helpers.rest_client.auth.BearerTokenAuth
    """

    def __init__(self, token: str):
        self.token = token

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


class APIKeyAuth(AuthBase):
    """API key authentication.

    Compatible with dlt.sources.helpers.rest_client.auth.APIKeyAuth
    """

    def __init__(
        self,
        api_key: str,
        name: str = "Authorization",
        location: str = "header",
    ):
        self.api_key = api_key
        self.name = name
        self.location = location

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        if self.location == "header":
            request.headers[self.name] = self.api_key
        elif self.location == "query":
            # Add to query params
            if request.url and "?" in request.url:
                request.url = f"{request.url}&{self.name}={self.api_key}"
            else:
                request.url = f"{request.url}?{self.name}={self.api_key}"
        elif self.location == "cookie":
            if "Cookie" in request.headers:
                request.headers["Cookie"] += f"; {self.name}={self.api_key}"
            else:
                request.headers["Cookie"] = f"{self.name}={self.api_key}"
        return request


class HttpBasicAuth(AuthBase):
    """HTTP Basic authentication.

    Compatible with dlt.sources.helpers.rest_client.auth.HttpBasicAuth
    """

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        credentials = f"{self.username}:{self.password}"
        encoded = base64.b64encode(credentials.encode("ascii")).decode("ascii")
        request.headers["Authorization"] = f"Basic {encoded}"
        return request


# Alias for compatibility
AuthConfigBase = AuthBase
