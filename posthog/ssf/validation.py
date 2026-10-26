import re
from ipaddress import ip_address
from typing import Literal, cast
from urllib.parse import urlsplit

from django.db import models
from django.views.decorators.debug import sensitive_variables

import jwt
from pydantic import BaseModel, ConfigDict, Field, JsonValue

PUSH_DELIVERY = "urn:ietf:rfc:8935"
POLL_DELIVERY = "urn:ietf:rfc:8936"
VERIFICATION_EVENT = "https://schemas.openid.net/secevent/ssf/event-type/verification"
STREAM_UPDATED_EVENT = "https://schemas.openid.net/secevent/ssf/event-type/stream-updated"
CONTROL_EVENTS = [VERIFICATION_EVENT, STREAM_UPDATED_EVENT]
RETENTION_DAYS = 30
MAX_TOKEN_BYTES = 65536
EVENT_TYPE_PATTERN = r"^[a-zA-Z][a-zA-Z0-9+.-]*:[^\s]+$"
SUBJECT_MEMBERS = {"user", "device", "session", "application", "tenant", "org_unit", "group"}
SUBJECT_FIELDS = {
    "account": ("uri",),
    "email": ("email",),
    "iss_sub": ("iss", "sub"),
    "opaque": ("id",),
    "phone_number": ("phone_number",),
    "did": ("url",),
    "uri": ("uri",),
    "jwt_id": ("iss", "jti"),
    "saml_assertion_id": ("issuer", "assertion_id"),
}


class SSFOutgoingEventType(models.TextChoices):
    SESSION_REVOKED = "https://schemas.openid.net/secevent/caep/event-type/session-revoked", "Session revoked (CAEP)"
    ACCOUNT_ENABLED = "https://schemas.openid.net/secevent/risc/event-type/account-enabled", "Account enabled (RISC)"
    ACCOUNT_DISABLED = "https://schemas.openid.net/secevent/risc/event-type/account-disabled", "Account disabled (RISC)"
    CREDENTIAL_COMPROMISE = (
        "https://schemas.openid.net/secevent/risc/event-type/credential-compromise",
        "Credential compromise (RISC)",
    )


class SSFStreamEventType(models.TextChoices):
    VERIFICATION = VERIFICATION_EVENT, "Verification"
    STREAM_UPDATED = STREAM_UPDATED_EVENT, "Stream updated"
    SESSION_REVOKED = SSFOutgoingEventType.SESSION_REVOKED.value, SSFOutgoingEventType.SESSION_REVOKED.label
    ACCOUNT_ENABLED = SSFOutgoingEventType.ACCOUNT_ENABLED.value, SSFOutgoingEventType.ACCOUNT_ENABLED.label
    ACCOUNT_DISABLED = SSFOutgoingEventType.ACCOUNT_DISABLED.value, SSFOutgoingEventType.ACCOUNT_DISABLED.label
    CREDENTIAL_COMPROMISE = (
        SSFOutgoingEventType.CREDENTIAL_COMPROMISE.value,
        SSFOutgoingEventType.CREDENTIAL_COMPROMISE.label,
    )


class PublicRSAJWK(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kty: Literal["RSA"]
    n: str = Field(min_length=1, max_length=2048)
    e: str = Field(min_length=1, max_length=16)
    kid: str = Field(default="", max_length=255)
    alg: Literal["RS256"] = "RS256"
    use: Literal["sig"] = "sig"


class PublicECJWK(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kty: Literal["EC"]
    crv: Literal["P-256"]
    x: str = Field(min_length=1, max_length=128)
    y: str = Field(min_length=1, max_length=128)
    kid: str = Field(default="", max_length=255)
    alg: Literal["ES256"] = "ES256"
    use: Literal["sig"] = "sig"


class PublicJWKS(BaseModel):
    keys: list[PublicRSAJWK | PublicECJWK] = Field(min_length=0, max_length=50)


def is_event_type(value: str) -> bool:
    return re.fullmatch(EVENT_TYPE_PATTERN, value) is not None


def _validate_https_url(value: str, message: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(message)
    return value


def validate_issuer(value: str) -> str:
    return _validate_https_url(value, "Enter an HTTPS issuer URL without credentials, a query, or a fragment.")


def validate_transmitter_url(value: str) -> str:
    return _validate_https_url(
        value, "Enter an HTTPS transmitter metadata URL without credentials, a query, or a fragment."
    )


@sensitive_variables("value", "key", "normalized")
def validate_jwks(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
        raise ValueError("Enter a JSON Web Key Set with a keys array.")
    for key in value["keys"]:
        if not isinstance(key, dict) or {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}.intersection(key):
            raise ValueError("Use public signing keys only. Do not include private key material.")
    supported = [
        key
        for key in value["keys"]
        if key.get("use", "sig") == "sig"
        and (
            (key.get("kty") == "RSA" and key.get("alg", "RS256") == "RS256")
            or (key.get("kty") == "EC" and key.get("crv") == "P-256" and key.get("alg", "ES256") == "ES256")
        )
    ]
    normalized = PublicJWKS.model_validate({"keys": supported}).model_dump()
    ids = [key["kid"] for key in normalized["keys"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Each signing key must have a distinct key ID.")
    if not normalized["keys"]:
        raise ValueError("Configure at least one public signing key for the trusted transmitter.")
    for key_data in normalized["keys"]:
        key = jwt.PyJWK.from_dict(key_data)
        if key.key_type == "RSA" and key.key.key_size < 2048:
            raise ValueError("Use RSA signing keys of at least 2048 bits.")
    return cast(dict[str, JsonValue], normalized)


def validate_subject(value: object, *, critical_members: list[str] | None = None) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError("The subject must be an object.")
    subject_format = value.get("format")
    if subject_format == "complex":
        members = {name: member for name, member in value.items() if name != "format"}
        if not members:
            raise ValueError("A complex subject must contain at least one member.")
        for name, member in members.items():
            if critical_members is not None and name in critical_members and name not in SUBJECT_MEMBERS:
                raise ValueError("The subject contains an unsupported critical member.")
            if not isinstance(member, dict) or member.get("format") == "complex":
                raise ValueError("Complex subject members must be simple subjects.")
            try:
                validate_subject(member)
            except ValueError:
                if critical_members is None or name in critical_members:
                    raise
    elif subject_format == "ip-addresses":
        addresses = value.get("ip-addresses")
        if (
            not isinstance(addresses, list)
            or not addresses
            or not all(isinstance(address, str) for address in addresses)
        ):
            raise ValueError("An IP address subject must contain an array of IP addresses.")
        for address in addresses:
            ip_address(address)
    elif isinstance(subject_format, str) and subject_format in SUBJECT_FIELDS:
        if any(not isinstance(value.get(field), str) or not value[field] for field in SUBJECT_FIELDS[subject_format]):
            raise ValueError("The subject is missing a required identifier.")
    else:
        raise ValueError("The subject identifier format is not supported.")
    return cast(dict[str, JsonValue], value)


def subjects_match(first: dict[str, JsonValue], second: dict[str, JsonValue]) -> bool:
    if first.get("format") != "complex" or second.get("format") != "complex":
        return first == second
    return all(first[name] == second[name] for name in first.keys() & second.keys() if name != "format")
