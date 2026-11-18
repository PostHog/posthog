"""Exact rules that flag a hog function beside Jev's answers, so a probe is caught even when the model call fails.

Pure: no database, no DNS lookup, no network.
"""

import re
import json
import ipaddress
from collections.abc import Iterable, Iterator
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from posthog.security.oob_domains import matched_oob_domain
from posthog.security.url_validation import canonicalize_host, internal_host_name

from products.cdp.backend.abuse.classifier import MAX_STATE_CHARS, HogFunctionContent
from products.ml_inference.backend.facade.contracts import JsonValue


class Rule(StrEnum):
    # A destination sends a request to our own network: an input value or a literal `fetch` URL names the host.
    INTERNAL_HOST = "internal_host"
    # Any other internal URL, such as a transformation that drops events from `http://localhost:3000`.
    INTERNAL_HOST_REFERENCE = "internal_host_reference"
    REQUEST_CATCHER = "request_catcher"
    OVERSIZED_INPUT = "oversized_input"


# Every rule alerts. Customers test destinations against request catchers, send large inputs and filter out
# local traffic, so only a request to our own network is certain enough to block.
BLOCKING_RULES = frozenset({Rule.INTERNAL_HOST})

# Jev reads at most this much state, so an input longer than that can never be shown to it whole.
OVERSIZED_INPUT_CHARS = MAX_STATE_CHARS

# Request inspection and tunnel services. The out-of-band interaction domains in `oob_domains.json` count too.
_REQUEST_CATCHER_DOMAINS = frozenset(
    {
        "webhook.site",
        "httpbin.org",
        "requestcatcher.com",
        "srv.us",
        "loca.lt",
        "trycloudflare.com",
        "ngrok.io",
        "ngrok.app",
        "ngrok.dev",
        "ngrok-free.app",
        "ngrok-free.dev",
    }
)

_SCHEME = re.compile(r"https?://", re.IGNORECASE)
# Only the authority after each scheme is read. It holds no "/", so two authorities never overlap and the scan stays
# linear. A URL nested in the query of another URL has its own scheme, so it is read on its own.
_AUTHORITY = re.compile(r"[^\s\"'`<>(){},;/?#\\]+")
_FETCH_LITERAL = re.compile(r"""\bfetch\s*\(\s*f?(?:'((?:[^'\\]++|\\.)*+)'|"((?:[^"\\]++|\\.)*+)")""", re.DOTALL)
# A URL can hide inside a query parameter of another URL, encoded once per layer of redirect.
_MAX_DECODE_PASSES = 3
_IPV4_PART = {16: re.compile(r"[0-9a-f]*"), 8: re.compile(r"[0-7]+"), 10: re.compile(r"[0-9]+")}


def matched_rules(content: HogFunctionContent) -> tuple[Rule, ...]:
    target_hosts = set(_hosts_in(_request_targets(content)))
    hosts = target_hosts | set(_hosts_in(_texts(content)))
    matched = set()
    if any(_is_internal(host) for host in target_hosts):
        matched.add(Rule.INTERNAL_HOST)
    elif any(_is_internal(host) for host in hosts):
        matched.add(Rule.INTERNAL_HOST_REFERENCE)
    if any(_is_request_catcher(host) for host in hosts):
        matched.add(Rule.REQUEST_CATCHER)
    if any(_encoded_length(value) > OVERSIZED_INPUT_CHARS for value in _input_values(content)):
        matched.add(Rule.OVERSIZED_INPUT)
    return tuple(rule for rule in Rule if rule in matched)


def _all_inputs(content: HogFunctionContent) -> Iterator[JsonValue]:
    yield from content.inputs.values()
    for mapping in content.mappings:
        if isinstance(mapping, dict) and isinstance(inputs := mapping.get("inputs"), dict):
            yield from inputs.values()


def _input_values(content: HogFunctionContent) -> Iterator[JsonValue]:
    for entry in _all_inputs(content):
        if isinstance(entry, dict):
            yield entry.get("value")


def _request_targets(content: HogFunctionContent) -> Iterator[str]:
    """The strings a destination sends a request to. A transformation runs without network access."""
    if content.type != "destination":
        return
    yield from _strings(list(_all_inputs(content)))
    yield from (literal.group(1) or literal.group(2) or "" for literal in _FETCH_LITERAL.finditer(content.hog))


def _texts(content: HogFunctionContent) -> Iterator[str]:
    """The strings that run or reach a request. Filters are left out, because they only match events, and an
    event filter on a local `$current_url` is ordinary."""
    yield content.hog
    yield from _strings(list(_all_inputs(content)))
    yield from _strings(content.masking)


def _strings(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _hosts_in(texts: Iterable[str]) -> Iterator[str]:
    for text in texts:
        yield from _url_hosts(text)


def _url_hosts(text: str) -> Iterator[str]:
    for layer in _decoded_layers(text):
        for scheme in _SCHEME.finditer(layer):
            authority = _AUTHORITY.match(layer, scheme.end())
            if authority is None:
                continue
            try:
                parts = urlsplit(f"http://{authority.group()}")
            except ValueError:
                continue
            if parts.hostname:
                yield parts.hostname
            # `http://169.254.169.254@example.com` connects to example.com, but probes how a parser reads userinfo.
            if parts.username:
                yield parts.username


def _decoded_layers(text: str) -> Iterator[str]:
    yield text
    for _ in range(_MAX_DECODE_PASSES):
        decoded = unquote(text)
        if decoded == text:
            return
        yield decoded
        text = decoded


def _is_internal(host: str) -> bool:
    if internal_host_name(host) is not None:
        return True
    # The URL parser maps the host to ASCII before it reads an address, so `127。1` and fullwidth digits count.
    shorthand = _runtime_ipv4(canonicalize_host(host))
    return shorthand is not None and internal_host_name(str(shorthand)) is not None


def _runtime_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """The address a WHATWG URL parser, such as the one in Node, reads from `127.1`, `2130706433` or `0x7f000001`."""
    parts = host.lower().split(".")
    if len(parts) > 1 and parts[-1] == "":
        parts.pop()
    if not 1 <= len(parts) <= 4:
        return None
    numbers = [_ipv4_number(part) for part in parts]
    if any(number is None for number in numbers):
        return None
    *leading, last = [number for number in numbers if number is not None]
    if any(number > 255 for number in leading) or last >= 256 ** (5 - len(parts)):
        return None
    return ipaddress.IPv4Address(last + sum(number << (8 * (3 - index)) for index, number in enumerate(leading)))


def _ipv4_number(part: str) -> int | None:
    if part.startswith("0x"):
        base, digits = 16, part[2:]
    elif len(part) > 1 and part.startswith("0"):
        base, digits = 8, part[1:]
    else:
        base, digits = 10, part
    # An IPv4 part never needs more than 11 significant digits, and `int` refuses strings past its digit limit.
    if len(digits.lstrip("0")) > 11 or not _IPV4_PART[base].fullmatch(digits):
        return None
    return int(digits, base) if digits else 0


def _is_request_catcher(host: str) -> bool:
    canonical = canonicalize_host(host)
    in_catcher_domain = any(
        canonical == domain or canonical.endswith(f".{domain}") for domain in _REQUEST_CATCHER_DOMAINS
    )
    return in_catcher_domain or matched_oob_domain(canonical) is not None


def _encoded_length(value: JsonValue) -> int:
    return len(value) if isinstance(value, str) else len(json.dumps(value, ensure_ascii=False, default=str))
