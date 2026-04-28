from base64 import b64encode
from typing import Literal, Optional

from requests import PreparedRequest
from requests.auth import AuthBase

TApiKeyLocation = Literal["header", "query", "param", "cookie"]


class AuthConfigBase(AuthBase):
    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        return request

    def __bool__(self) -> bool:
        return True


class BearerTokenAuth(AuthConfigBase):
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


class APIKeyAuth(AuthConfigBase):
    def __init__(
        self,
        api_key: Optional[str] = None,
        name: str = "Authorization",
        location: TApiKeyLocation = "header",
    ) -> None:
        self.api_key = api_key
        self.name = name
        self.location = location

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if self.location == "header":
            request.headers[self.name] = self.api_key or ""
        elif self.location in ("query", "param"):
            request.prepare_url(request.url, {self.name: self.api_key})
        elif self.location == "cookie":
            request.prepare_cookies({self.name: self.api_key or ""})
        return request


class HttpBasicAuth(AuthConfigBase):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.username = username
        self.password = password

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        encoded = b64encode(f"{self.username}:{self.password}".encode()).decode()
        request.headers["Authorization"] = f"Basic {encoded}"
        return request
