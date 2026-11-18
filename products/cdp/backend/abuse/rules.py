"""Exact rules that flag a hog function beside Jev's answers, so a probe is caught even when the model call fails.

Pure: no database, no DNS lookup, no network.
"""

import re
import json
from collections.abc import Iterator
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from posthog.security.oob_domains import matched_oob_domain
from posthog.security.url_validation import canonicalize_host, internal_host_name

from products.cdp.backend.abuse.classifier import MAX_STATE_CHARS, HogFunctionContent
from products.ml_inference.backend.facade.contracts import JsonValue


class Rule(StrEnum):
    INTERNAL_HOST = "internal_host"
    REQUEST_CATCHER = "request_catcher"
    OVERSIZED_INPUT = "oversized_input"


# Every rule alerts. Customers test destinations against request catchers and send large inputs, so only a
# request to our own network is certain enough to block.
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

# A lookahead, so a URL nested in the query of another URL is matched on its own too.
_URL = re.compile(r"(?=(https?://[^\s\"'`<>(){},;]+))", re.IGNORECASE)
# A URL can hide inside a query parameter of another URL, encoded once per layer of redirect.
_MAX_DECODE_PASSES = 3


def matched_rules(content: HogFunctionContent) -> tuple[Rule, ...]:
    hosts = {host for text in _texts(content) for host in _url_hosts(text)}
    matched = set()
    if any(internal_host_name(host) is not None for host in hosts):
        matched.add(Rule.INTERNAL_HOST)
    if any(_is_request_catcher(host) for host in hosts):
        matched.add(Rule.REQUEST_CATCHER)
    if any(_encoded_length(value) > OVERSIZED_INPUT_CHARS for value in _input_values(content)):
        matched.add(Rule.OVERSIZED_INPUT)
    return tuple(rule for rule in Rule if rule in matched)


def _all_inputs(content: HogFunctionContent) -> Iterator[JsonValue]:
    yield from content.inputs.values()
    for mapping in content.mappings:
        if isinstance(mapping, dict) and isinstance(mapping.get("inputs"), dict):
            yield from mapping["inputs"].values()


def _input_values(content: HogFunctionContent) -> Iterator[JsonValue]:
    for entry in _all_inputs(content):
        if isinstance(entry, dict):
            yield entry.get("value")


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


def _url_hosts(text: str) -> Iterator[str]:
    for layer in _decoded_layers(text):
        for url in _URL.findall(layer):
            try:
                parts = urlsplit(url)
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


def _is_request_catcher(host: str) -> bool:
    canonical = canonicalize_host(host)
    in_catcher_domain = any(
        canonical == domain or canonical.endswith(f".{domain}") for domain in _REQUEST_CATCHER_DOMAINS
    )
    return in_catcher_domain or matched_oob_domain(canonical) is not None


def _encoded_length(value: JsonValue) -> int:
    return len(value) if isinstance(value, str) else len(json.dumps(value, ensure_ascii=False, default=str))
