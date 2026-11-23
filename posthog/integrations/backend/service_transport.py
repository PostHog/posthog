"""Signed HTTP requests to the integrations routes of the credentials service.

`ServiceTransport` mints the EdDSA tokens, sends the requests, and maps the errors of the service to
SDK exceptions. `ServiceBackend` uses it to read and write rows.
"""

import time
import uuid
import builtins
import functools
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, NoReturn

from django.conf import settings

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from posthog.credentials_service.callers import CredentialsCaller
from posthog.integrations.contracts import IntegrationConflict, IntegrationNotFound, UnsupportedAuthType
from posthog.integrations.secret_reads import UndecryptedIntegrationSecretError
from posthog.jwt import PosthogJwtAudience
from posthog.security.outbound_proxy import internal_requests

INTEGRATIONS_PATH = "/v1/integrations"
# Integrations tokens use an asymmetric algorithm, so the service holds only the public key.
TOKEN_ALGORITHM = "EdDSA"
# The service rejects a token that lives longer than 60 seconds.
TOKEN_LIFETIME_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 5
REQUEST_ATTEMPTS = 2

ServiceOp = Literal[
    "read",
    "write",
    "delete",
    "resolve",
    "list_across_teams",
    "read_by_external_id",
    "write_by_external_id",
    "delete_by_external_id",
]

# Keyed by the step of an SDK operation that one token covers. A token with no owner may hold only
# cross-team ops, so a step that reads rows of every team and a step that resolves the secrets of one
# team get separate tokens.
_OPS: dict[str, tuple[ServiceOp, ...]] = {
    # `resolve` returns a row with its secrets. `read` loads a row whose secret the service cannot decrypt.
    "get": ("resolve", "read"),
    "get_many": ("resolve", "read"),
    "resolve": ("resolve", "read"),
    "find": ("read",),
    "list": ("read",),
    "exists": ("read",),
    "count": ("read",),
    "list_across_teams": ("list_across_teams",),
    "read_by_external_id": ("read_by_external_id",),
    "create": ("write",),
    "upsert": ("write",),
    # A write reads the row first, to check the scope and to send its version in `If-Match`.
    "update": ("read", "write"),
    "delete": ("read", "delete"),
    "update_by_external_id": ("write_by_external_id",),
    "delete_by_external_id": ("delete_by_external_id",),
}


_CROSS_TEAM_OPS = frozenset(
    {"list_across_teams", "read_by_external_id", "write_by_external_id", "delete_by_external_id"}
)


def _ops_for(operation: str) -> tuple[ServiceOp, ...]:
    """The service ops that the token of one step of an SDK operation holds. Each token allows only these."""
    return _OPS[operation]


class IntegrationServiceError(Exception):
    """The credentials service refused a request, and no SDK exception fits the reason.

    `code` is the error code of the service, for example `forbidden_op` or `validation`. These
    errors come from configuration or from a bug in the client, not from the row.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@functools.cache
def _load_signing_key(path: str) -> Ed25519PrivateKey:
    """Reads the Ed25519 private key of this deployment from a mounted file, once per process."""
    try:
        with open(path, "rb") as key_file:
            key = load_pem_private_key(key_file.read(), password=None)
    except (OSError, ValueError, TypeError) as error:
        raise IntegrationServiceError(
            "unconfigured",
            f"CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH must name a readable PEM Ed25519 private key file ({type(error).__name__})",
        ) from error
    if not isinstance(key, Ed25519PrivateKey):
        raise IntegrationServiceError(
            "unconfigured", "CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH must hold an Ed25519 private key"
        )
    return key


class IntegrationServiceUnavailable(IntegrationServiceError):
    """The credentials service did not answer, failed, or could not reach its key service. Retry later."""


class _VersionMismatch(IntegrationConflict):
    """The row changed after the backend read it. A write reads the row again."""


def _raise_for_error(response: requests.Response) -> NoReturn:
    code, message = "unknown", f"status {response.status_code}"
    try:
        error = response.json()["error"]
        code, message = str(error["code"]), str(error.get("message") or message)
    except (ValueError, KeyError, TypeError):
        # A rejected token gets a bare 401, with no JSON body.
        if response.status_code == 401:
            code = "unauthorized"
    if code in ("not_found", "forbidden_kind"):
        # A row of a kind that the token does not name is out of the scope of the accessor.
        raise IntegrationNotFound(message)
    if code == "version_mismatch":
        raise _VersionMismatch(message)
    if code == "conflict":
        raise IntegrationConflict(message)
    if code == "unsupported_auth_type":
        raise UnsupportedAuthType(message)
    if code == "unreadable_secret":
        raise UndecryptedIntegrationSecretError()
    if code == "kms_unavailable" or response.status_code >= 500:
        raise IntegrationServiceUnavailable(code, message)
    raise IntegrationServiceError(code, message)


class ServiceTransport:
    """Signs and sends requests to the integrations routes. Safe to share between threads."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        caller: CredentialsCaller = CredentialsCaller.INTEGRATIONS,
    ) -> None:
        self._session = session or internal_requests
        self._caller = caller

    def token(
        self,
        operation: str,
        *,
        team_id: int | None,
        kinds: Iterable[str] | None = None,
        refs: Iterable[str] | None = None,
        user_id: int | None = None,
    ) -> Callable[[], str]:
        ops = builtins.list(_ops_for(operation))
        # Each token has one owner. Only a cross-team token has none.
        if (team_id is None) != _CROSS_TEAM_OPS.issuperset(ops):
            raise ValueError(f"Operation {operation!r} and team_id={team_id!r} do not match")
        kind_claim = None if kinds is None else sorted(set(kinds))
        ref_claim = None if refs is None else sorted(set(refs))

        def mint() -> str:
            if not settings.CREDENTIALS_SERVICE_URL or not settings.CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH:
                raise IntegrationServiceError(
                    "unconfigured",
                    "Set CREDENTIALS_SERVICE_URL and CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH",
                )
            signing_key = _load_signing_key(settings.CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH)
            issued_at = int(time.time())
            claims: dict[str, Any] = {
                "aud": PosthogJwtAudience.CREDENTIALS_SERVICE_INTEGRATIONS.value,
                "iat": issued_at,
                "exp": issued_at + TOKEN_LIFETIME_SECONDS,
                # The service accepts each jti once.
                "jti": uuid.uuid4().hex,
                "ops": ops,
                "caller": str(self._caller),
            }
            if team_id is not None:
                claims["owner"] = {"type": "team", "id": team_id}
            if kind_claim is not None:
                claims["kinds"] = kind_claim
            if ref_claim is not None:
                claims["refs"] = ref_claim
            if user_id is not None:
                claims["user_id"] = user_id
            return jwt.encode(claims, signing_key, algorithm=TOKEN_ALGORITHM)

        return mint

    def request(
        self,
        method: str,
        path: str,
        token: Callable[[], str],
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        not_found_ok_on_retry: bool = False,
    ) -> requests.Response | None:
        url = f"{settings.CREDENTIALS_SERVICE_URL.rstrip('/')}{INTEGRATIONS_PATH}{path}"
        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            # A new token for each attempt: the service may have used the jti of the first one.
            request_headers = {"Authorization": f"Bearer {token()}", **(headers or {})}
            try:
                response = self._session.request(
                    method, url, params=params, json=body, headers=request_headers, timeout=REQUEST_TIMEOUT_SECONDS
                )
            except requests.ConnectionError as error:
                if attempt < REQUEST_ATTEMPTS:
                    continue
                raise IntegrationServiceUnavailable(
                    "unreachable", f"{method} {path}: {type(error).__name__}"
                ) from error
            except requests.RequestException as error:
                raise IntegrationServiceUnavailable(
                    "unreachable", f"{method} {path}: {type(error).__name__}"
                ) from error
            if response.status_code < 400:
                return response
            # The first attempt may have deleted the row before the connection dropped.
            if not_found_ok_on_retry and attempt > 1 and response.status_code == 404:
                return None
            _raise_for_error(response)
        raise AssertionError("unreachable")

    def json(self, method: str, path: str, token: Callable[[], str], **kwargs: Any) -> Any:
        response = self.request(method, path, token, **kwargs)
        try:
            return response.json() if response is not None else None
        except ValueError as error:
            raise IntegrationServiceUnavailable("bad_response", f"{method} {path} did not answer JSON") from error
