"""How a template declares the use of a stored credential, so the worker applies it and the code never reads it.

A secret input or an integration input carries an `auth` declaration. Code passes the input to `fetch` as
`{'auth': inputs.<key>}`, and the worker sets the credential on the request when its origin matches the binding.

- An integration's origins and placement come from its kind, in the worker. Its declaration names the placement
  that kind uses and must not name origins.
- A secret's origins come from the declaration, or from the URL input that `origin_input` names. The declaration is
  bound to the secret when someone types it, and stored with it, so a later edit of the schema or the URL input
  cannot move the secret to another origin.
"""

import re
from typing import Any

from django.db import models

from rest_framework import serializers


class AuthScheme(models.TextChoices):
    BEARER = "bearer", "bearer"
    HEADER = "header", "header"
    BASIC = "basic", "basic"
    QUERY = "query", "query"
    BODY = "body", "body"


SCHEMES = tuple(AuthScheme.values)
# A credential in the query string or the body sits next to text the code chooses, so a template opts in to these.
OPT_IN_SCHEMES = ("query", "body")
MAX_ORIGINS = 10

_KEYS_BY_SCHEME: dict[str, set[str]] = {
    "bearer": set(),
    "header": {"name", "prefix"},
    "basic": {"username_input", "username_field", "password_field"},
    "query": {"name", "opt_in"},
    "body": {"path", "opt_in"},
}
_SECRET_KEYS = {"origins", "origin_input"}
_INTEGRATION_KEYS = {"field"}

# An HTTP token, as RFC 9110 defines a header name.
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
# The worker routes the request by these, and the HTTP client sets the framing ones itself.
_RESERVED_HEADERS = {"host", ":authority", "content-length", "transfer-encoding", "connection", "cookie"}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")

_SCHEME = re.compile(r"(https?)://", re.IGNORECASE)
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_UNSAFE_AUTHORITY = re.compile(r"[@\\%\s\x00-\x1f\x7f]")
_NUMERIC_LABEL = re.compile(r"^(\d+|0x[0-9a-f]*)$")


def url_origin(url: str) -> str | None:
    """`scheme://host[:port]` as the worker's WHATWG parser reads the URL, or None when the two could disagree."""
    scheme = _SCHEME.match(url)
    if not scheme:
        return None
    rest = url[scheme.end() :]
    end = min((index for index in (rest.find(c) for c in "/?#") if index >= 0), default=len(rest))
    authority = rest[:end]
    # Python's IDNA codec and the WHATWG URL parser map some non-ASCII hosts differently.
    if not authority or not authority.isascii() or _UNSAFE_AUTHORITY.search(authority):
        return None
    host, _, port = authority.lower().rpartition(":") if ":" in authority else (authority.lower(), "", "")
    if port and not (port.isdigit() and not port.startswith("0") and int(port) <= 65535):
        return None
    host = host.rstrip(".")
    if not host or not _is_canonical_host(host):
        return None
    scheme_name = scheme.group(1).lower()
    origin = f"{scheme_name}://{host}"
    return origin if not port or port == _DEFAULT_PORTS[scheme_name] else f"{origin}:{port}"


# The worker's WHATWG parser rewrites IPv6 and short or hex IPv4 hosts, so only a dotted quad keeps its text.
def _is_canonical_host(host: str) -> bool:
    if host.startswith("["):
        return False
    labels = host.split(".")
    if not _NUMERIC_LABEL.match(labels[-1]):
        return True
    return len(labels) == 4 and all(
        label.isdigit() and str(int(label)) == label and int(label) <= 255 for label in labels
    )


class AuthDeclaration:
    """Validates the `auth` entry of one input schema item against the rest of the schema."""

    declaration: dict[str, Any]

    def __init__(self, schema_item: dict[str, Any], schemas: list[dict[str, Any]]) -> None:
        self.item = schema_item
        self.schemas_by_key = {str(schema.get("key")): schema for schema in schemas if isinstance(schema, dict)}

    def validate(self) -> None:
        declaration = self.item.get("auth")
        if not isinstance(declaration, dict):
            raise serializers.ValidationError("auth must be an object.")
        self.declaration = declaration
        scheme = declaration.get("scheme")
        if scheme not in SCHEMES:
            raise serializers.ValidationError(f"auth.scheme must be one of: {', '.join(SCHEMES)}.")

        is_integration = self.item.get("type") == "integration"
        if not is_integration and not (self.item.get("secret") and self.item.get("type") == "string"):
            raise serializers.ValidationError("auth can only be set on a secret string input or an integration input.")
        allowed = _KEYS_BY_SCHEME[scheme] | {"scheme"} | (_INTEGRATION_KEYS if is_integration else _SECRET_KEYS)
        unknown = set(declaration) - allowed
        if unknown:
            raise serializers.ValidationError(f"auth does not accept {', '.join(sorted(unknown))} here.")

        if scheme in OPT_IN_SCHEMES and declaration.get("opt_in") is not True:
            raise serializers.ValidationError(f"auth.scheme {scheme} needs auth.opt_in set to true.")
        if scheme in ("header", "query"):
            self._validate_name(scheme)
        if scheme == "header" and not isinstance(declaration.get("prefix", ""), str):
            raise serializers.ValidationError("auth.prefix must be text.")
        if scheme == "body":
            self._validate_body_path()
        if scheme == "basic":
            self._validate_basic(is_integration)
        if is_integration:
            self._validate_identifier("field", required=False)
        else:
            self._validate_secret_origins()

    def _validate_name(self, scheme: str) -> None:
        name = self.declaration.get("name")
        if not isinstance(name, str) or not _HEADER_NAME.match(name):
            raise serializers.ValidationError(f"auth.name must name the {scheme} parameter.")
        if scheme == "header" and name.lower() in _RESERVED_HEADERS:
            raise serializers.ValidationError(f"auth.name can't be the {name} header.")

    def _validate_body_path(self) -> None:
        path = self.declaration.get("path")
        # The worker writes the path into a JavaScript object, where `__proto__` sets the prototype instead of a key.
        parts = path.split(".") if isinstance(path, str) else []
        if not parts or not all(_IDENTIFIER.match(part) and part != "__proto__" for part in parts):
            raise serializers.ValidationError("auth.path must be a dotted path of JSON keys, such as data.token.")

    def _validate_basic(self, is_integration: bool) -> None:
        if is_integration:
            self._validate_identifier("username_field", required=True)
            self._validate_identifier("password_field", required=False)
            return
        username_input = self.declaration.get("username_input")
        username_schema = self.schemas_by_key.get(username_input) if isinstance(username_input, str) else None
        # The username is not bound, so it must not be a secret that could carry another credential.
        if not username_schema or username_schema.get("secret") or username_schema.get("type") != "string":
            raise serializers.ValidationError("auth.username_input must name a string input that is not secret.")

    def _validate_identifier(self, key: str, required: bool) -> None:
        value = self.declaration.get(key)
        if value is None and not required:
            return
        if not isinstance(value, str) or not _IDENTIFIER.match(value):
            raise serializers.ValidationError(f"auth.{key} must name a connection field.")

    def _validate_secret_origins(self) -> None:
        origins = self.declaration.get("origins")
        origin_input = self.declaration.get("origin_input")
        if (origins is None) == (origin_input is None):
            raise serializers.ValidationError("auth needs either origins or origin_input.")
        if origin_input is not None:
            origin_schema = self.schemas_by_key.get(origin_input) if isinstance(origin_input, str) else None
            if not origin_schema or origin_schema.get("secret") or origin_schema.get("type") != "string":
                raise serializers.ValidationError("auth.origin_input must name a string input that is not secret.")
            return
        if not isinstance(origins, list) or not origins or len(origins) > MAX_ORIGINS:
            raise serializers.ValidationError(f"auth.origins must list 1 to {MAX_ORIGINS} origins.")
        for origin in origins:
            if not isinstance(origin, str) or url_origin(origin) != origin or not origin.startswith("https://"):
                raise serializers.ValidationError(
                    f"auth.origins must hold origins like https://api.example.com, not {origin}."
                )


def validate_auth_declarations(schemas: Any) -> None:
    if not isinstance(schemas, list):
        return
    errors = {}
    for item in schemas:
        if isinstance(item, dict) and "auth" in item:
            try:
                AuthDeclaration(item, schemas).validate()
            except serializers.ValidationError as error:
                errors[str(item.get("key"))] = error.detail
    if errors:
        raise serializers.ValidationError({"auth": errors})


def bind_secret_auth(declaration: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """The declaration to store with a secret the user just typed, with its origins resolved for the worker."""
    bound = {key: value for key, value in declaration.items() if key not in _SECRET_KEYS}
    origin_input = declaration.get("origin_input")
    if origin_input is None:
        return {**bound, "origins": list(declaration["origins"])}
    entry = inputs.get(origin_input)
    url = entry.get("value") if isinstance(entry, dict) else None
    origin = url_origin(url) if isinstance(url, str) and "{" not in url else None
    if not origin or not origin.startswith("https://"):
        raise serializers.ValidationError(
            f"Enter a full address in {origin_input}, starting with https://, before you save this secret."
        )
    return {**bound, "origins": [origin]}
