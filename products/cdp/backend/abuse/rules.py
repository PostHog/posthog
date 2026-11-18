"""Exact rules that flag a hog function beside Jev's answers, so a probe is caught even when the model call fails.

Pure: no database, no DNS lookup, no network.
"""

import re
import json
import math
import ipaddress
from collections.abc import Iterable, Iterator
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from posthog.hogql import ast
from posthog.hogql.parser import parse_program
from posthog.hogql.visitor import TraversingVisitor

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
    INTERNAL_FUNCTION = "internal_function"
    HUGE_RANGE = "huge_range"
    # `replaceAll(s, '', t)` inserts `t` before every character of `s`, so the string grows with each call.
    REPLACE_AMPLIFICATION = "replace_amplification"


# Every rule alerts. Customers test destinations against request catchers, send large inputs and filter out
# local traffic, so only a request to our own network is certain enough to block.
BLOCKING_RULES = frozenset({Rule.INTERNAL_HOST})

# Jev reads at most this much state, so an input longer than that can never be shown to it whole.
OVERSIZED_INPUT_CHARS = MAX_STATE_CHARS

# Every async function registered in `nodejs/src/cdp/async-functions/` except `fetch`, so keep the two in sync. Each one
# backs a hidden workflow or warehouse-webhook template, so code a customer wrote rarely has a reason to call one.
INTERNAL_FUNCTIONS = frozenset(
    {
        "postHogAddToStaticCohort",
        "postHogClassify",
        "postHogCreateAccount",
        "postHogCreateCustomerTask",
        "postHogCreateTask",
        "postHogGetAccount",
        "postHogGetTicket",
        "postHogOptOutOfMessages",
        "postHogReplayVisionScan",
        "postHogRunScout",
        "postHogSendTicketMessage",
        "postHogSetAccountProperties",
        "postHogUpdateAccount",
        "postHogUpdateTicket",
        "produceToWarehouseWebhooks",
        "sendEmail",
        "sendPushNotification",
    }
)

# A range runs or allocates every element on each event. Templates loop over a handful of items, and this is far
# below the Liquid and Hog memory limits, so a larger range probes those limits instead of building a payload.
MAX_RANGE_SIZE = 10_000

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

# The runtime URL parser skips every slash and backslash after the scheme, so `http:////127.0.0.1` reaches loopback.
_SCHEME = re.compile(r"https?:[/\\]+", re.IGNORECASE)
# The authority runs to the path, query or fragment, so userinfo such as `u;v@` keeps the host after it. Parentheses
# end it too, so a Markdown link keeps its host. It holds no slash, so two authorities never overlap and the scan
# stays linear. A nested URL has its own scheme.
_AUTHORITY = re.compile(r"[^\s\"'`<>()/\\?#]+")
_FETCH_LITERAL = re.compile(r"""\bfetch\s*\(\s*f?(?:'((?:[^'\\]++|\\.)*+)'|"((?:[^"\\]++|\\.)*+)")""", re.DOTALL)
# A URL can hide inside a query parameter of another URL, encoded once per layer of redirect.
_MAX_DECODE_PASSES = 3
_IPV4_PART = {16: re.compile(r"[0-9a-f]*"), 8: re.compile(r"[0-7]+"), 10: re.compile(r"[0-9]+")}
_LIQUID_OPENER = re.compile(r"\{[{%]")
_QUOTE = re.compile(r"['\"]")
_LIQUID_STRING_PATTERN = r"""'(?:[^'\\]++|\\.)*+'|"(?:[^"\\]++|\\.)*+\""""
_LIQUID_STRING = re.compile(_LIQUID_STRING_PATTERN, re.DOTALL)
# LiquidJS reads the inside of these blocks as text, so no expression in them runs.
_LIQUID_BLOCK_ENDS = {
    "comment": re.compile(r"\{%-?\s*endcomment\b"),
    "raw": re.compile(r"\{%-?\s*endraw\b"),
}
_LIQUID_BOUND = rf"""([+-]?\d++(?:\.(?!\.)\d*+)?|{_LIQUID_STRING_PATTERN})"""
# A quoted string is matched first so that a range written inside one is skipped as text.
_LIQUID_STRING_OR_RANGE = re.compile(
    rf"""{_LIQUID_STRING_PATTERN}|\(\s*+{_LIQUID_BOUND}\s*+\.\.\s*+{_LIQUID_BOUND}\s*+\)""", re.DOTALL
)
_JS_DECIMAL = re.compile(r"[+-]?(?:\d++(?:\.\d*+)?|\.\d++)(?:e[+-]?\d++)?", re.IGNORECASE)
_JS_PREFIXED_INTEGER = re.compile(r"0x[0-9a-f]++|0o[0-7]++|0b[01]++", re.IGNORECASE)
_JS_INFINITY = {"Infinity": math.inf, "+Infinity": math.inf, "-Infinity": -math.inf}


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
    if any(_has_huge_liquid_range(text) for text in _liquid_templates(content)):
        matched.add(Rule.HUGE_RANGE)
    # Unedited template code is PostHog's, such as the hidden workflow templates that call internal functions.
    if content.code_modified_from_template is not False:
        matched |= _hog_code_rules(content.hog)
    return tuple(rule for rule in Rule if rule in matched)


def _hog_code_rules(hog: str) -> set[Rule]:
    """The rules that need the parsed code, so a name in a string, a comment or a property never counts. Code that
    does not parse matches none of them, and the API refuses to save it."""
    try:
        program = parse_program(hog)
    except Exception:
        return set()
    visitor = _HogCodeVisitor()
    visitor.visit(program)
    return visitor.matched


class _HogCodeVisitor(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.matched: set[Rule] = set()

    def visit_call(self, node: ast.Call) -> None:
        super().visit_call(node)
        if node.name in INTERNAL_FUNCTIONS:
            self.matched.add(Rule.INTERNAL_FUNCTION)
        elif node.name == "range" and _hog_range_size(node.args) > MAX_RANGE_SIZE:
            self.matched.add(Rule.HUGE_RANGE)
        elif node.name == "replaceAll" and _replaces_empty_string(node.args):
            self.matched.add(Rule.REPLACE_AMPLIFICATION)

    def visit_field(self, node: ast.Field) -> None:
        # `let run := postHogCreateTask` followed by `run()` reaches the same handler as a direct call.
        super().visit_field(node)
        if len(node.chain) == 1 and str(node.chain[0]) in INTERNAL_FUNCTIONS:
            self.matched.add(Rule.INTERNAL_FUNCTION)


def _hog_range_size(args: list[ast.Expr]) -> float:
    """The length of `range(end)` or `range(start, end)` with literal bounds, as the Hog VM in Node computes it."""
    bounds = [bound for bound in map(_number_constant, args[:2]) if bound is not None]
    if not bounds or len(bounds) != min(len(args), 2):
        return 0
    size = bounds[0] if len(bounds) == 1 else bounds[1] - bounds[0]
    return math.trunc(size) if math.isfinite(size) else size


def _number_constant(expr: ast.Expr) -> float | None:
    if not isinstance(expr, ast.Constant) or isinstance(expr.value, bool):
        return None
    if isinstance(expr.value, int | float):
        return _to_float(expr.value)
    if isinstance(expr.value, str):
        return _js_number(expr.value)
    return None


def _replaces_empty_string(args: list[ast.Expr]) -> bool:
    if len(args) != 3:
        return False
    return _is_empty_string(args[1]) and not _is_empty_string(args[2])


def _is_empty_string(expr: ast.Expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value == ""


def _liquid_templates(content: HogFunctionContent) -> Iterator[str]:
    """The input strings that the runtime renders with Liquid. Any other templating reads a range as plain text."""
    for entry in _all_inputs(content):
        if isinstance(entry, dict) and entry.get("templating") == "liquid":
            yield from _strings(entry.get("value"))


def _has_huge_liquid_range(template: str) -> bool:
    for tag in _liquid_tags(template):
        for match in _LIQUID_STRING_OR_RANGE.finditer(tag):
            if match.group(1) is None:
                continue
            low, high = (_liquid_number(bound) for bound in match.groups())
            # LiquidJS builds the list from `low` while the value stays below `high + 1`.
            if high - low + 1 > MAX_RANGE_SIZE:
                return True
    return False


def _liquid_tags(template: str) -> Iterator[str]:
    """The inside of each output and logic tag that LiquidJS evaluates, in document order. Comments and raw blocks
    are left out. A template that LiquidJS cannot tokenize ends the scan, because none of it renders."""
    position = 0
    while (opener := _LIQUID_OPENER.search(template, position)) is not None:
        is_output = opener.group() == "{{"
        end = _output_tag_end(template, opener.end()) if is_output else template.find("%}", opener.end())
        if end == -1:
            return
        tag = template[opener.end() : end]
        position = end + 2
        words = tag.lstrip("-").split(maxsplit=1)
        name = words[0] if words else ""
        if name.startswith("#"):
            continue
        if not is_output and (block_end := _LIQUID_BLOCK_ENDS.get(name)) is not None:
            closing = block_end.search(template, position)
            closing_end = -1 if closing is None else template.find("%}", closing.end())
            if closing_end == -1:
                return
            position = closing_end + 2
            continue
        yield tag


def _output_tag_end(template: str, start: int) -> int:
    """Where the output tag that starts at `start` closes, or -1. The LiquidJS tokenizer skips a `}}` inside a quoted
    string here, though not in a logic tag. Each search starts where the last one stopped, so the scan stays linear."""
    position = start
    close = template.find("}}", position)
    while close != -1:
        quote = _QUOTE.search(template, position, close)
        if quote is None:
            return close
        string = _LIQUID_STRING.match(template, quote.start())
        if string is None:
            return -1
        position = string.end()
        if position > close:
            close = template.find("}}", position)
    return -1


def _liquid_number(bound: str) -> float:
    return _js_number(bound[1:-1] if bound[0] in "'\"" else bound)


def _js_number(text: str) -> float:
    """What JavaScript's `Number` makes of a string, NaN when it is not a number."""
    text = text.strip()
    if not text:
        return 0.0
    if _JS_DECIMAL.fullmatch(text):
        return float(text)
    if _JS_PREFIXED_INTEGER.fullmatch(text):
        return _to_float(int(text, 0))
    return _JS_INFINITY.get(text, math.nan)


def _to_float(number: int | float) -> float:
    try:
        return float(number)
    except OverflowError:
        return math.inf if number > 0 else -math.inf


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
