"""Client authentication primitives shared by every OAuth token consumer.

Both the oauthlib-backed ``/oauth/token`` endpoint and the hand-rolled agentic token
endpoint have to answer the same question -- has this client proven it is who it claims to
be -- so the comparison itself lives here rather than being written once per endpoint.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import field
from typing import Any
from urllib.parse import unquote_plus

from django.contrib.auth.hashers import check_password, identify_hasher
from django.utils.crypto import constant_time_compare

from posthog.dataclasses import frozen

BASIC_PREFIX = "Basic "


@frozen
class ClientCredentials:
    client_id: str
    # repr=False keeps the secret out of logs and tracebacks.
    client_secret: str = field(repr=False)


def verify_client_secret(provided_secret: str, stored_secret: str) -> bool:
    """Check a presented client secret against the stored one.

    Mirrors oauth2_provider's ``OAuth2Validator._check_secret`` so hashed and legacy
    unhashed secrets both verify, but fails closed when either side is blank.

    The blank guard is what the library is missing, and it is load-bearing. An application
    created with ``client_secret=""`` does not store an empty string: ``ClientSecretField``
    runs ``make_password("")`` on save, so the column holds a valid hash *of* the empty
    string. ``check_password("", <hash of "">)`` is ``True``, so without this guard a client
    that presents no secret at all authenticates as any such application. Applications
    registered for ``private_key_jwt`` are exactly that shape, since their proof is a signed
    assertion and they never receive a secret.
    """
    if not provided_secret or not stored_secret:
        return False

    try:
        identify_hasher(stored_secret)
    except ValueError:
        # Raised when the stored secret was never hashed.
        return constant_time_compare(provided_secret, stored_secret)
    return check_password(provided_secret, stored_secret)


def client_credentials_from_basic_auth(request: Any) -> ClientCredentials | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith(BASIC_PREFIX):
        return None

    try:
        decoded = base64.b64decode(auth_header[len(BASIC_PREFIX) :].strip()).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None

    client_id, separator, client_secret = decoded.partition(":")
    if not separator or not client_id or not client_secret:
        return None

    # RFC 6749 section 2.3.1 requires both halves to be form-urlencoded before they are
    # base64'd, so a secret containing ":" survives the split above.
    return ClientCredentials(client_id=unquote_plus(client_id), client_secret=unquote_plus(client_secret))


def extract_client_credentials(request: Any) -> ClientCredentials | None:
    """Return the client_id and client_secret the request presents, or None.

    Both RFC 6749 transports are accepted. Basic auth is read first because the GitHub
    grant listing endpoint is a GET, which has no body to carry the pair.
    """
    from_basic = client_credentials_from_basic_auth(request)
    if from_basic is not None:
        return from_basic

    client_id = request.data.get("client_id") or ""
    client_secret = request.data.get("client_secret") or ""
    if client_id and client_secret:
        return ClientCredentials(client_id=client_id, client_secret=client_secret)

    return None
