"""The canvas platform contract, loaded from the builder package's manifest.

manifest.json is the single source of truth shared by the Node builder
(build.mjs), this Python validator/build service, and the artifact origin's
CSP. The desktop app asserts its own copy against the same file in a contract
test, so a drift in pinned dependencies or limits fails loudly instead of
diverging silently.
"""

import re
import json
import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings

CANVAS_BUILDER_DIR = Path(settings.CANVAS_BUILDER_DIR)

GRID_COLUMN_CHOICES = (4, 6, 8, 10, 12)
MAX_COMPONENT_WIDTH = max(GRID_COLUMN_CHOICES)
MAX_COMPONENT_HEIGHT = 40

# A public DNS name is one or more dot-separated labels of ASCII letters, digits,
# and hyphens (IDNA names stay in this set), with an optional trailing dot. Any
# other character is rejected because urlsplit keeps CSP delimiters such as ";"
# and spaces inside the netloc, so an origin like "example.com; img-src evil.net"
# would otherwise reach the hostname unchanged and inject an extra directive when
# spliced into the artifact's resource directives.
_DNS_NAME_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_DNS_NAME_RE = re.compile(rf"{_DNS_NAME_LABEL}(?:\.{_DNS_NAME_LABEL})*\.?")


@lru_cache(maxsize=1)
def platform_contract() -> dict[str, Any]:
    return json.loads((CANVAS_BUILDER_DIR / "manifest.json").read_text())


def platform_dependencies() -> dict[str, str]:
    """Pinned name → exact version of every platform-supported dependency."""
    return {name: entry["version"] for name, entry in platform_contract()["dependencies"].items()}


def allowed_import_specifiers() -> frozenset[str]:
    return frozenset(platform_contract()["allowedImportSpecifiers"])


def _is_public_network_host(hostname: str) -> bool:
    """Reject hosts that point at the viewer's machine or private network.

    Declared origins go straight into the viewer's CSP, so a loopback or
    private origin would let a published canvas probe services on the viewer's
    machine or LAN. Literal IPs must be globally routable; names must be dotted
    public DNS names outside the reserved local suffixes. Rebinding a public
    name to a private address is out of scope for publish-time validation — that
    needs resolver or network-level controls.
    """
    try:
        address = ipaddress.ip_address(hostname)
        # A zone-scoped literal ("%eth0") is never a routable public origin,
        # and the free-form scope text would otherwise reach the CSP verbatim.
        return address.is_global and getattr(address, "scope_id", None) is None
    except ValueError:
        pass
    # Browsers resolve "localhost." like "localhost", so a trailing dot must
    # not dodge the checks below — require the canonical spelling outright.
    if hostname.endswith("."):
        return False
    if not _DNS_NAME_RE.fullmatch(hostname):
        return False
    if "." not in hostname:
        return False
    # Browsers parse a numeric or 0x-hex final label as an IPv4 address
    # ("127.1", "0177.0.0.1", "0x7f.0.0.1") while a real DNS TLD is never
    # all digits — only strict dotted-decimal literals may take the IP branch.
    if re.fullmatch(r"[0-9]+|0x[0-9a-f]*", hostname.rsplit(".", 1)[-1]):
        return False
    return not hostname.endswith((".local", ".localhost", ".internal", ".home.arpa"))


def canonical_network_origin(origin: Any) -> str | None:
    if not isinstance(origin, str):
        return None
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "*" in parsed.hostname
        or not _is_public_network_host(parsed.hostname.lower())
    ):
        return None
    hostname = f"[{parsed.hostname.lower()}]" if ":" in parsed.hostname else parsed.hostname.lower()
    return f"https://{hostname}" + (f":{port}" if port is not None else "")


def artifact_csp(network_origins: list[str] | None = None) -> str:
    csp = platform_contract()["csp"]
    safe_origins = [canonical for origin in network_origins or [] if (canonical := canonical_network_origin(origin))]
    if not safe_origins:
        return csp
    sources = " ".join(safe_origins)
    replacements = {
        "connect-src 'none'": f"connect-src {sources}",
        "style-src 'self' 'unsafe-inline'": f"style-src 'self' 'unsafe-inline' {sources}",
        "img-src 'self' data: blob:": f"img-src 'self' data: blob: {sources}",
        "font-src 'self' data:": f"font-src 'self' data: {sources}",
        "media-src 'self' data: blob:": f"media-src 'self' data: blob: {sources}",
        "frame-src 'none'": f"frame-src {sources}",
    }
    for directive, replacement in replacements.items():
        csp = csp.replace(directive, replacement)
    return csp


def contract_limits() -> dict[str, int]:
    return platform_contract()["limits"]


def canvas_sdk_version() -> str:
    return platform_contract()["canvasSdkVersion"]
