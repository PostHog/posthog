"""Follows the W3C Device Bound Session Credentials editor's draft: https://w3c.github.io/webappsec-dbsc/"""

import re
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from posthog.dataclasses import frozen
from posthog.session.dbsc.binding import Algorithm, Binding
from posthog.session.dbsc.cookies import cookie_attributes, cookie_name
from posthog.session.dbsc.paths import REFRESH_PATH, START_PATH

REGISTRATION_HEADER = "Secure-Session-Registration"
CHALLENGE_HEADER = "Secure-Session-Challenge"
RESPONSE_HEADER = "Secure-Session-Response"
SESSION_ID_HEADER = "Sec-Secure-Session-Id"
SKIPPED_HEADER = "Secure-Session-Skipped"

_PROOF_TYPE = "dbsc+jwt"
# Only these members describe the key. Anything else the browser sends is not stored on the session row.
_KEY_MEMBERS: dict[Algorithm, tuple[str, ...]] = {"ES256": ("kty", "crv", "x", "y"), "RS256": ("kty", "n", "e")}
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")
_MIN_RSA_KEY_BITS = 2048


class ProofError(Exception):
    pass


@frozen
class Proof:
    alg: Algorithm
    jti: str
    jwk: dict[str, Any] | None


def registration_header_value(challenge: str) -> str:
    return f'(ES256 RS256);path="{START_PATH}";challenge="{challenge}"'


def challenge_header_value(challenge: str, binding_id: str) -> str:
    return f'"{challenge}";id="{binding_id}"'


def parse_sf_string(value: str | None) -> str | None:
    """Bare values are accepted too, because earlier drafts did not quote them."""
    if value is None:
        return None
    value = value.strip()
    if not value.startswith('"'):
        bare = value.split(";", 1)[0].strip()
        return bare or None
    chars: list[str] = []
    escaped = False
    for char in value[1:]:
        if escaped:
            chars.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return "".join(chars) or None
        else:
            chars.append(char)
    return None


def _proof_header(token: str) -> tuple[Algorithm, dict[str, Any]]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as error:
        raise ProofError("malformed") from error
    if header.get("typ") != _PROOF_TYPE:
        raise ProofError("wrong_type")
    alg = header.get("alg")
    if alg not in ("ES256", "RS256"):
        raise ProofError("unsupported_algorithm")
    return cast(Algorithm, alg), header


def _public_key(alg: Algorithm, jwk: object) -> jwt.PyJWK:
    if not isinstance(jwk, dict):
        raise ProofError("missing_key")
    if "d" in jwk:
        raise ProofError("private_key")
    if alg == "ES256" and (jwk.get("kty") != "EC" or jwk.get("crv") != "P-256"):
        raise ProofError("wrong_key_type")
    if alg == "RS256" and jwk.get("kty") != "RSA":
        raise ProofError("wrong_key_type")
    # pyjwt's base64 decoding skips characters outside the alphabet, so a NUL could reach the stored key.
    for member in _KEY_MEMBERS[alg][1:]:
        value = jwk.get(member)
        if member != "crv" and not (isinstance(value, str) and _BASE64URL.fullmatch(value)):
            raise ProofError("malformed_key")
    try:
        key = jwt.PyJWK(jwk, algorithm=alg)
    except (jwt.PyJWTError, TypeError, ValueError) as error:
        raise ProofError("malformed_key") from error
    if isinstance(key.key, RSAPublicKey) and key.key.key_size < _MIN_RSA_KEY_BITS:
        raise ProofError("weak_key")
    return key


def _verified_jti(token: str, key: jwt.PyJWK, alg: Algorithm) -> str:
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[alg],
            # The draft defines only `jti`, and its examples send `iat` as a string.
            options={
                "require": ["jti"],
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except jwt.InvalidSignatureError as error:
        raise ProofError("bad_signature") from error
    except jwt.PyJWTError as error:
        raise ProofError("invalid") from error
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        raise ProofError("missing_challenge")
    return jti


def verify_registration_proof(token: str) -> Proof:
    """The caller still checks the challenge."""
    alg, header = _proof_header(token)
    jwk = header.get("jwk")
    key = _public_key(alg, jwk)
    public_jwk = {member: cast(dict[str, Any], jwk)[member] for member in _KEY_MEMBERS[alg]}
    return Proof(alg=alg, jti=_verified_jti(token, key, alg), jwk=public_jwk)


def verify_refresh_proof(token: str, binding: Binding) -> Proof:
    alg, _ = _proof_header(token)
    if alg != binding.alg:
        raise ProofError("algorithm_changed")
    key = _public_key(alg, binding.jwk)
    return Proof(alg=alg, jti=_verified_jti(token, key, alg), jwk=None)


def session_config(binding_id: str) -> dict[str, Any]:
    """Without `scope.origin`, the session covers the origin that served the registration."""
    return {
        "session_identifier": binding_id,
        "refresh_url": REFRESH_PATH,
        "scope": {
            "include_site": False,
            "scope_specification": [{"type": "exclude", "path": "/static"}],
        },
        "credentials": [{"type": "cookie", "name": cookie_name(), "attributes": cookie_attributes()}],
    }
