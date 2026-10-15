import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import field
from threading import local
from typing import Literal
from weakref import finalize

from openfga_sdk.client.configuration import ClientConfiguration
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.sync import OpenFgaClient as SdkOpenFgaClient

from posthog.dataclasses import frozen

DEFAULT_OPENFGA_STORE_NAME = "posthog-authz"
Consistency = Literal["MINIMIZE_LATENCY", "HIGHER_CONSISTENCY"]
CheckOptions = dict[str, int | str | dict[str, int | str]]


class OpenFgaClient(SdkOpenFgaClient):
    def __init__(self, configuration: ClientConfiguration, *, consistency: Consistency = "MINIMIZE_LATENCY") -> None:
        if consistency not in ("MINIMIZE_LATENCY", "HIGHER_CONSISTENCY"):
            raise ValueError("Unsupported OpenFGA consistency")
        super().__init__(configuration)
        self.consistency = consistency

    def _get_consistency(self, options: CheckOptions | None = None) -> str:
        # The SDK has no client-wide default, so use the hook shared by its read methods.
        return super()._get_consistency(options) or self.consistency


@frozen
class _ClientScope:
    pid: int
    api_url: str
    api_token: str | None = field(repr=False)
    store_id: str | None
    authorization_model_id: str | None
    store_name: str
    consistency: Consistency

    @classmethod
    def from_environment(cls, consistency: Consistency) -> "_ClientScope":
        return cls(
            pid=os.getpid(),
            api_url=os.getenv("OPENFGA_API_URL", "http://127.0.0.1:8080"),
            api_token=os.getenv("OPENFGA_API_TOKEN"),
            store_id=os.getenv("OPENFGA_STORE_ID"),
            authorization_model_id=os.getenv("OPENFGA_AUTHORIZATION_MODEL_ID"),
            store_name=os.getenv("OPENFGA_STORE_NAME") or DEFAULT_OPENFGA_STORE_NAME,
            consistency=consistency,
        )


def _create_client(scope: _ClientScope) -> OpenFgaClient:
    credentials = (
        Credentials(method="api_token", configuration=CredentialConfiguration(api_token=scope.api_token))
        if scope.api_token
        else Credentials()
    )
    client = OpenFgaClient(
        ClientConfiguration(
            api_url=scope.api_url,
            store_id=scope.store_id,
            authorization_model_id=scope.authorization_model_id,
            credentials=credentials,
            timeout_millisec=5000,
        ),
        consistency=scope.consistency,
    )
    if scope.store_id is None:
        try:
            stores = client.list_stores({"name": scope.store_name}).stores or []
            store = next((store for store in stores if store.name == scope.store_name), None)
            if store is not None:
                client.set_store_id(store.id)
        except Exception:
            client.close()
            raise
    return client


def get_openfga_client(*, consistency: Consistency = "MINIMIZE_LATENCY") -> OpenFgaClient:
    return _create_client(_ClientScope.from_environment(consistency))


class _CachedClient:
    def __init__(self, scope: _ClientScope) -> None:
        self.scope = scope
        self.client = _create_client(scope)
        self.borrowers = 0
        # Thread-local ownership releases sockets on thread exit; finalize also runs at process exit.
        self.close = finalize(self, self.client.close)


_clients = local()


def close_cached_openfga_client() -> None:
    cached: _CachedClient | None = getattr(_clients, "cached", None)
    if cached is not None:
        if cached.borrowers:
            raise RuntimeError("Cannot close an OpenFGA client while it is in use")
        cached.close()
        del _clients.cached


@contextmanager
def pooled_openfga_client(*, consistency: Consistency = "MINIMIZE_LATENCY") -> Iterator[OpenFgaClient]:
    scope = _ClientScope.from_environment(consistency)
    cached: _CachedClient | None = getattr(_clients, "cached", None)
    if cached is not None and cached.scope != scope:
        if cached.borrowers and cached.scope.pid == scope.pid:
            client = _create_client(scope)
            try:
                yield client
            finally:
                client.close()
            return
        cached.close()
        del _clients.cached
        cached = None
    if cached is None:
        cached = _CachedClient(scope)
        _clients.cached = cached
    cached.borrowers += 1
    try:
        yield cached.client
    finally:
        cached.borrowers -= 1
        # Retry discovery after bootstrap instead of retaining a client with no store.
        if not cached.borrowers and cached.client.get_store_id() is None:
            close_cached_openfga_client()
