"""Exact rules that flag a hog function beside Jev's answers, so a probe is caught even when the model call fails.

Pure: no database, no DNS lookup, no network.
"""

import re
import math
import ipaddress
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import SplitResult, unquote, urlsplit

import tldextract

from posthog.hogql import ast
from posthog.hogql.parser import CacheOrigin, parse_program, parse_string_template
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.schema_enums import ParserMode
from posthog.security.oob_domains import matched_oob_domain
from posthog.security.url_validation import canonicalize_host, has_authority_bypass_chars, internal_host_name

from products.cdp.backend.abuse.classifier import HogFunctionContent, SetAsideReason
from products.ml_inference.backend.facade.contracts import JsonValue

from common.hogvm.python.stl import STL
from common.hogvm.python.stl.bytecode import BYTECODE_STL


class Rule(StrEnum):
    # A destination sends a request to our own network: an input value or a literal `fetch` URL names the host.
    INTERNAL_HOST = "internal_host"
    # Any other internal URL, such as a transformation that drops events from `http://localhost:3000`.
    INTERNAL_HOST_REFERENCE = "internal_host_reference"
    REQUEST_CATCHER = "request_catcher"
    SECURITY_CALLBACK = "security_callback"
    INTERNAL_FUNCTION = "internal_function"
    HUGE_RANGE = "huge_range"
    # `replaceAll(s, '', t)` inserts `t` before every character of `s`, so the string grows with each call.
    REPLACE_AMPLIFICATION = "replace_amplification"


# Every rule alerts. Customers test destinations against request catchers and filter out local traffic, so only a
# request to our own network is certain enough to block.
BLOCKING_RULES = frozenset({Rule.INTERNAL_HOST})

# Async functions that back a hidden workflow, customer analytics or warehouse-webhook template, so code a customer
# wrote rarely has a reason to call one. Functions meant for customer code, such as the ticket functions, stay out.
INTERNAL_FUNCTIONS = frozenset(
    {
        "postHogAddToStaticCohort",
        "postHogClassify",
        "postHogCreateAccount",
        "postHogCreateCustomerTask",
        "postHogCreateTask",
        "postHogGetAccount",
        "postHogOptOutOfMessages",
        "postHogReplayVisionScan",
        "postHogRunScout",
        "postHogSetAccountProperties",
        "postHogUpdateAccount",
        "produceToWarehouseWebhooks",
        "sendEmail",
        "sendPushNotification",
    }
)

# Every async function in `nodejs/src/cdp/async-functions/`, and `postHogCapture`. A function added there must be
# added here too, or code that calls only that function counts as making no outbound call.
OUTBOUND_FUNCTIONS = INTERNAL_FUNCTIONS | {
    "fetch",
    "postHogCapture",
    "postHogGetTicket",
    "postHogSendTicketMessage",
    "postHogUpdateTicket",
}

# A function from one of these templates runs plugin, Segment or native destination code instead of its `hog` field.
_NON_HOG_TEMPLATE_PREFIXES = ("plugin-", "segment-", "native-")

_CALLBACK_FUNCTIONS = frozenset({"arrayCount", "arrayExists", "arrayFilter", "arrayMap", "arrayReduce"})
_BUILTIN_FUNCTIONS = frozenset(STL) | frozenset(BYTECODE_STL)

# Source that names none of these cannot match a rule that reads parsed Hog, so it is not parsed.
_HOG_RULE_NAMES = re.compile("|".join(sorted(INTERNAL_FUNCTIONS | {"range", "replaceAll"})))

# A range runs or allocates every element on each event. Templates loop over a handful of items, and this is far
# below the Liquid and Hog memory limits, so a larger range probes those limits instead of building a payload.
MAX_RANGE_SIZE = 10_000

# Request inspection and tunnel services.
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

# Not in `oob_domains.json`, because its other readers refuse every host on it and this rule only alerts.
_SECURITY_CALLBACK_DOMAINS = frozenset({"bxss.me", "canarytokens.com", "canarytokens.org", "requestrepo.com", "xss.ht"})
_SECURITY_CALLBACK_TOOL_NAME = re.compile(r"(?:^|[.-])(?:xsshunter|xss-hunter|interactsh)(?:$|[.-])")

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
_LIQUID_TEXT_BLOCKS = frozenset({"comment", "raw"})
# The characters LiquidJS skips as blanks, which are not the characters `\s` matches.
_LIQUID_BLANKS = "\t\n\v\f\r \xa0\u1680\u180e\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
_LIQUID_BLANK = rf"[{_LIQUID_BLANKS}]"
# A LiquidJS tag name is `#` for an inline comment, or a run of word characters, which include `?`, `-` and any
# character past ASCII that is not a blank or a curly double quote.
_LIQUID_WORD_CHAR = rf"(?:[-0-9?A-Z_a-z]|[^\x00-\x7f{_LIQUID_BLANKS}\u201c\u201d])"
_LIQUID_TAG_NAME = re.compile(rf"{_LIQUID_BLANK}*+(#|{_LIQUID_WORD_CHAR}*+)")
# LiquidJS reads each statement of a `{% liquid %}` block as a tag, which drops a leading `-` as whitespace control.
_LIQUID_STATEMENT_TRIM = re.compile(rf"\A{_LIQUID_BLANK}*+-")
# LiquidJS reads `{%- endraw` and `endraw-` as other identifiers, so neither of them ends a raw block.
_LIQUID_RAW_END = re.compile(rf"\{{%{_LIQUID_BLANK}*endraw(?!{_LIQUID_WORD_CHAR})")
_LIQUID_DELIMITER = re.compile(r"%\}|\{%")
_LIQUID_BOUND = rf"""([+-]?\d++(?:\.(?!\.)\d*+)?|{_LIQUID_STRING_PATTERN})"""
_LIQUID_RANGE = re.compile(rf"""\(\s*+{_LIQUID_BOUND}\s*+\.\.\s*+{_LIQUID_BOUND}\s*+\)""", re.DOTALL)
_LIQUID_STRING_OR_PAREN = re.compile(r"['\"(]")
_LIQUID_STRING_ESCAPE = re.compile(r"\\(?:u([0-9a-fA-F]{0,4})|([0-7]{1,3})|(.))", re.DOTALL)
_LIQUID_ESCAPED_CHARS = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
# `LiquidRenderer` in `nodejs/src/cdp/utils/liquid.ts` decodes these inside each tag before LiquidJS reads it.
_DECODED_ENTITIES = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#x27;", "'"), ("&amp;", "&"))
_DECODED_TAG_CLOSERS = {"{": "}}", "%": "%}"}
_QUOTE_OR_ENCODED_SPACE = re.compile(r"['\"]|%20")
_JS_DECIMAL = re.compile(r"[+-]?(?:\d++(?:\.\d*+)?|\.\d++)(?:e[+-]?\d++)?", re.IGNORECASE)
_JS_PREFIXED_INTEGER = re.compile(r"0x[0-9a-f]++|0o[0-7]++|0b[01]++", re.IGNORECASE)
_JS_INFINITY = {"Infinity": math.inf, "+Infinity": math.inf, "-Infinity": -math.inf}

# The endpoints that post a message to a chat channel, as a host and the whole path. Other endpoints on these hosts,
# such as file uploads, OAuth or Telegram's `setWebhook`, do more than post text.
_CHAT_MESSAGE_APIS = (
    ("slack.com", re.compile(r"/api/chat\.postMessage")),
    ("hooks.slack.com", re.compile(r"/services/[^/]+/[^/]+/[^/]+")),
    ("discord.com", re.compile(r"/api/webhooks/[^/]+/[^/]+")),
    ("api.telegram.org", re.compile(r"/bot[^/]+/sendMessage")),
    ("chat.googleapis.com", re.compile(r"/v1/spaces/[^/]+/messages")),
)
_TEAMS_WEBHOOK_DOMAIN = ".webhook.office.com"
_TEAMS_WEBHOOK_PATH = re.compile(r"/webhookb2/[^/]+/IncomingWebhook/[^/]+/[^/]+(?:/[^/]+)?")
_INTERNAL_HOST_RULES = frozenset({Rule.INTERNAL_HOST, Rule.INTERNAL_HOST_REFERENCE})
# Public names that resolve to loopback, or to the address written in them as in `127.0.0.1.nip.io`.
_ADDRESS_DNS_DOMAINS = frozenset(
    {
        "localtest.me",
        "lvh.me",
        "vcap.me",
        "nip.io",
        "sslip.io",
        "xip.io",
        "traefik.me",
        "local.gd",
        "localhost.direct",
        "rbndr.us",
    }
)
_EMBEDDED_IPV4 = re.compile(r"(?<![0-9])[0-9]{1,3}(?:[.-][0-9]{1,3}){3}(?![0-9])|(?:^|\.)[0-9a-f]{8}(?:\.|$)")
# A DNS name whose last label starts with a letter, so neither the host nor its top-level label reads as an address.
_PUBLIC_DNS_NAME = re.compile(r"(?:[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?\.)+[a-z](?:[a-z0-9-]*[a-z0-9])?")
# The bundled public suffix list, so no lookup goes out and no cache file is written. A `.localhost` name or a cluster
# short name such as `redis.posthog` has no public suffix, but one whose namespace is also a top-level domain does.
_DOMAIN_PARTS = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=())
_URL_PART_SEPARATOR = re.compile(r"[^0-9a-z._:%\[\]-]+", re.IGNORECASE)
_BRACKETED_ADDRESS = re.compile(r"\[([^\[\]]*)\]")


def matched_rules(content: HogFunctionContent) -> tuple[Rule, ...]:
    url_inputs = _template_url_inputs(content)
    target_hosts = set(_hosts_in(_request_targets(content, url_inputs)))
    hosts = target_hosts | set(_hosts_in(_texts(content)))
    reference_hosts = target_hosts | set(_hosts_in(_texts(content, url_inputs)))
    matched = set()
    if any(_is_internal(host) for host in target_hosts):
        matched.add(Rule.INTERNAL_HOST)
    elif any(_is_internal(host) for host in reference_hosts):
        matched.add(Rule.INTERNAL_HOST_REFERENCE)
    if any(_is_request_catcher(host) for host in hosts):
        matched.add(Rule.REQUEST_CATCHER)
    if any(_is_security_callback(host) for host in hosts):
        matched.add(Rule.SECURITY_CALLBACK)
    if any(_has_huge_liquid_range(text) for text in _liquid_templates(content)):
        matched.add(Rule.HUGE_RANGE)
    # Unedited template code is PostHog's, such as the hidden workflow templates that call internal functions.
    if content.code_modified_from_template is not False:
        matched |= _hog_code_rules(_parse_code, content.hog)
    for template in _hog_templates(content):
        matched |= _hog_code_rules(_parse_template, template)
    return tuple(rule for rule in Rule if rule in matched)


def has_outbound_call(content: HogFunctionContent) -> bool:
    """Whether the code or a Hog template can call a function that sends a request. Code that does not parse counts,
    as does unedited template code, which still runs."""
    if (content.template_id or "").startswith(_NON_HOG_TEMPLATE_PREFIXES):
        return True
    return _calls_out(_parse_code, content.hog) or any(
        _calls_out(_parse_template, template) for template in _hog_templates(content)
    )


def set_aside_scores(content: HogFunctionContent, rule_hits: Iterable[Rule]) -> dict[str, SetAsideReason]:
    """The questions whose model score alone cannot alert, because the code shows the risk cannot happen. The score
    is still reported."""
    requests = _requests_of(content)
    if requests is None:
        return {}
    rules = frozenset(rule_hits)
    set_aside: dict[str, SetAsideReason] = {}
    if not requests.calls_out:
        set_aside["internal_network"] = SetAsideReason.NO_OUTBOUND_CALL
    elif (
        requests.only_literal_fetches
        and all(_is_literal_public_url(url) for url in requests.literal_urls)
        and not rules & _INTERNAL_HOST_RULES
    ):
        set_aside["internal_network"] = SetAsideReason.LITERAL_PUBLIC_URLS
    # A transformation returns its payload to ingestion whatever it posts to chat.
    if (
        content.type == "destination"
        and requests.calls_out
        and requests.only_literal_fetches
        and not requests.raw_body
        and all(map(_is_chat_message_api, requests.literal_urls))
    ):
        set_aside["malformed_payload"] = SetAsideReason.CHAT_MESSAGES_ONLY
    return set_aside


@frozen
class _Requests:
    calls_out: bool
    only_literal_fetches: bool
    literal_urls: tuple[str, ...]
    # A literal `fetch` may send a body that is not JSON: `fetch` sends a string body as it is.
    raw_body: bool


def _requests_of(content: HogFunctionContent) -> _Requests | None:
    """How the code and its Hog templates can send requests, or None when that cannot be read from the code."""
    if (content.template_id or "").startswith(_NON_HOG_TEMPLATE_PREFIXES):
        return None
    programs = [(_parse_code, content.hog), *((_parse_template, template) for template in _hog_templates(content))]
    shapes = []
    for parse, hog in programs:
        visitor = _HogCodeVisitor()
        try:
            visitor.visit(parse(hog))
        except Exception:
            return None
        shapes.append(visitor.requests())
    return _Requests(
        calls_out=any(shape.calls_out for shape in shapes),
        only_literal_fetches=all(shape.only_literal_fetches for shape in shapes),
        literal_urls=tuple(url for shape in shapes for url in shape.literal_urls),
        raw_body=any(shape.raw_body for shape in shapes),
    )


def _is_chat_message_api(url: str) -> bool:
    parts = _plain_url_parts(url)
    if parts is None or parts.scheme != "https" or parts.port not in (None, 443):
        return False
    # The runtime resolves `.` and `..` segments, also percent-encoded ones, before it sends, so `/api/../oauth`
    # reaches `/oauth`.
    if any(unquote(segment) in (".", "..") for segment in parts.path.split("/")):
        return False
    host = canonicalize_host(parts.hostname or "")
    if host.endswith(_TEAMS_WEBHOOK_DOMAIN):
        return _TEAMS_WEBHOOK_PATH.fullmatch(parts.path) is not None
    return any(host == api_host and path.fullmatch(parts.path) for api_host, path in _CHAT_MESSAGE_APIS)


def _is_literal_public_url(url: str) -> bool:
    """Whether a URL names a public DNS name, and no address, internal name or internal TLD anywhere in it, such as a
    redirect target in the query string."""
    parts = _plain_url_parts(url)
    if parts is None or parts.scheme not in ("http", "https"):
        return False
    host = canonicalize_host(parts.hostname or "")
    if _PUBLIC_DNS_NAME.fullmatch(host) is None or not _DOMAIN_PARTS(host).suffix:
        return False
    if _is_internal(host) or _resolves_to_its_address(host):
        return False
    return not any(_names_an_address(layer) for layer in _decoded_layers(url))


def _resolves_to_its_address(host: str) -> bool:
    in_address_domain = any(host == domain or host.endswith(f".{domain}") for domain in _ADDRESS_DNS_DOMAINS)
    return in_address_domain or _EMBEDDED_IPV4.search(host) is not None


def _plain_url_parts(url: str) -> SplitResult | None:
    """The parts of a URL that every parser reads the same way: no userinfo, whitespace, control character or
    backslash, and a valid port."""
    if has_authority_bypass_chars(url) or any(char.isspace() or not char.isprintable() for char in url):
        return None
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 -- raises for a port that is out of range or not a number
    except ValueError:
        return None
    if parts.username is not None or parts.password is not None or not parts.hostname:
        return None
    return parts._replace(scheme=parts.scheme.lower())


def _names_an_address(text: str) -> bool:
    if any(_is_ip(address) for address in _BRACKETED_ADDRESS.findall(text)):
        return True
    for part in _URL_PART_SEPARATOR.split(text):
        part = part.strip("[]")
        if _is_ip(part):
            return True
        for name in filter(None, part.split(":")):
            if internal_host_name(name) is not None or _is_address_shorthand(name):
                return True
    return False


def _is_address_shorthand(name: str) -> bool:
    """`1.2.3.4`, `127.1` or `0x7f000001`. A bare decimal such as an ID in a path is left out."""
    looks_like_an_address = "." in name or name.lower().startswith("0x")
    return looks_like_an_address and _runtime_ipv4(canonicalize_host(name)) is not None


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _calls_out(parse: Callable[[str], ast.AST], hog: str) -> bool:
    visitor = _HogCodeVisitor()
    try:
        visitor.visit(parse(hog))
    except Exception:
        return True
    return visitor.calls_out


def _parse_code(hog: str) -> ast.AST:
    """Parsed without the shadow parser and the parse cache, as is every template here. A shadow parse sends a
    diverging statement to error tracking, the cache keeps the statement in memory after the parse, and a template
    can be the decrypted value of a secret input."""
    return parse_program(hog, parser_mode=ParserMode.RUST_PY_ONLY, cache_origin=CacheOrigin.SENSITIVE)


def _parse_template(template: str) -> ast.AST:
    return parse_string_template(template, parser_mode=ParserMode.RUST_PY_ONLY, cache_origin=CacheOrigin.SENSITIVE)


def _hog_code_rules(parse: Callable[[str], ast.AST], hog: str) -> set[Rule]:
    """The rules that need the parsed code, so a name in a string, a comment or a property never counts. Code that
    does not parse matches none of them, and the API refuses to save it."""
    if _HOG_RULE_NAMES.search(hog) is None:
        return set()
    visitor = _HogCodeVisitor()
    try:
        visitor.visit(parse(hog))
    except Exception:
        # A parse error, or a tree too deep to walk. The compiler refuses both, so they never run.
        pass
    return visitor.matched


def _hog_templates(content: HogFunctionContent) -> Iterator[str]:
    """The Hog templates that run on every event besides the code: input values and the masking hash."""
    yield from _hog_template_inputs(content.inputs, content.inputs_schema)
    for mapping in content.mappings:
        if isinstance(mapping, dict):
            yield from _hog_template_inputs(mapping.get("inputs"), mapping.get("inputs_schema"))
    if isinstance(content.masking, dict) and isinstance(masking_hash := content.masking.get("hash"), str):
        yield masking_hash


def _hog_template_inputs(inputs: JsonValue, inputs_schema: JsonValue) -> Iterator[str]:
    if not isinstance(inputs, dict):
        return
    schema = inputs_schema if isinstance(inputs_schema, list) else []
    literal_keys = {item.get("key") for item in schema if isinstance(item, dict) and item.get("templating") is False}
    for key, entry in inputs.items():
        # The runtime renders an input with Hog unless it is Liquid or the input or its schema turns templating off.
        if isinstance(entry, dict) and key not in literal_keys and entry.get("templating") not in ("liquid", False):
            yield from (text for text in _strings(entry.get("value")) if "{" in text)


@dataclass(frozen=False, eq=False)
class _Binding:
    """One declared name. Calls resolve to the binding in scope, as the compiler resolves them, so two locals that
    share a name stay apart."""

    name: str
    # Declared with `fun`, or with `let` as a lambda literal, so a call runs a body this walk checks.
    declares_function: bool
    # Assigned, or used other than by a direct call. A value can be aliased and have its upvalues swapped, as in
    # `let alias := send` and `alias.upvalues[1] := ...`, so a call to it can run anything.
    rebound: bool = False
    # Declared with a dict literal and never replaced as a whole, so a write into it cannot reach a closure.
    holds_dict: bool = False
    replaced: bool = False

    @property
    def is_static_function(self) -> bool:
        return self.declares_function and not self.rebound


@dataclass(frozen=False)
class _CallGraph:
    """Which calls to locals can run something other than a body this walk checked."""

    calls: list[_Binding] = field(default_factory=list)
    # The targets of writes into a container. A write into anything but a dict literal can reach a closure's `upvalues`,
    # which points it at another closure's variables, so after one no local call is known.
    container_writes: list[_Binding | None] = field(default_factory=list)

    def requests(self, literal_urls: list[str], other_call: bool, raw_body: bool) -> _Requests:
        """A call to a static function runs its body, which this walk checked. A call to any other local can run
        anything, because the local can hold a closure from an input or have its upvalues swapped."""
        rewires = not all(map(_is_dict, self.container_writes))
        other_call |= any(rewires or not callee.is_static_function for callee in self.calls)
        return _Requests(
            calls_out=other_call or bool(literal_urls),
            only_literal_fetches=not other_call,
            literal_urls=tuple(literal_urls),
            raw_body=raw_body,
        )


def _is_dict(target: _Binding | None) -> bool:
    return target is not None and target.holds_dict and not target.replaced


class _HogCodeVisitor(TraversingVisitor):
    """Tracks the names in scope in source order, as the bytecode compiler does, because a call to a declared name
    runs the local and never reaches the standard library or the async function registry."""

    def __init__(self) -> None:
        super().__init__()
        self.matched: set[Rule] = set()
        self.calls_out = False
        self._scopes: list[dict[str, _Binding]] = [{}]
        self._literal_urls: list[str] = []
        self._raw_body = False
        # Locals passed as a `fetch` body. They go out as JSON while they still hold the dict literal they were declared
        # with when the walk ends, because a later replacement can run before the request.
        self._body_locals: list[_Binding] = []
        self._other_call = False
        self._graph = _CallGraph()

    def requests(self) -> _Requests:
        raw_body = self._raw_body or not all(map(_is_dict, self._body_locals))
        return self._graph.requests(self._literal_urls, self._other_call, raw_body)

    def _sends(self, literal_url: str | None = None) -> None:
        """A call here can send a request: a `fetch` of `literal_url`, or any call when it is None."""
        self.calls_out = True
        if literal_url is None:
            self._other_call = True
        else:
            self._literal_urls.append(literal_url)

    def _local(self, name: str) -> _Binding | None:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return None

    def _declare(self, name: str, *, declares_function: bool = False) -> _Binding:
        binding = _Binding(name=name, declares_function=declares_function)
        self._scopes[-1][name] = binding
        return binding

    @contextmanager
    def _scope(self, names: Iterable[str] = ()) -> Iterator[None]:
        self._scopes.append({name: _Binding(name=name, declares_function=False) for name in names})
        try:
            yield
        finally:
            self._scopes.pop()

    def visit_block(self, node: ast.Block) -> None:
        with self._scope():
            super().visit_block(node)

    def visit_function(self, node: ast.Function) -> None:
        self._declare(node.name, declares_function=True)
        with self._scope(node.params):
            super().visit_function(node)

    def visit_lambda(self, node: ast.Lambda) -> None:
        with self._scope(node.args):
            super().visit_lambda(node)

    def visit_for_in_statement(self, node: ast.ForInStatement) -> None:
        self.visit(node.expr)
        with self._scope([node.valueVar, *([node.keyVar] if node.keyVar else [])]):
            self.visit(node.body)

    def visit_for_statement(self, node: ast.ForStatement) -> None:
        with self._scope():
            super().visit_for_statement(node)

    def visit_try_catch_statement(self, node: ast.TryCatchStatement) -> None:
        self.visit(node.try_stmt)
        # The compiler declares `e` and `type` for every catch block.
        with self._scope(["e", "type"]):
            for name, _error_type, handler in node.catches:
                with self._scope([name] if name else []):
                    self.visit(handler)
        self.visit(node.finally_stmt)

    def visit_variable_declaration(self, node: ast.VariableDeclaration) -> None:
        # The compiler binds a lambda's name before its body, so the body can call itself.
        if isinstance(node.expr, ast.Lambda):
            self._declare(node.name, declares_function=True)
            self.visit(node.expr)
        else:
            super().visit_variable_declaration(node)
            self._declare(node.name).holds_dict = isinstance(node.expr, ast.Dict)

    def visit_variable_assignment(self, node: ast.VariableAssignment) -> None:
        super().visit_variable_assignment(node)
        if (name := _base_name(node.left)) is not None and (binding := self._local(name)) is not None:
            binding.rebound = True
            binding.replaced |= isinstance(node.left, ast.Field) and len(node.left.chain) == 1
        match node.left:
            case ast.Field(chain=[_]):
                pass
            case (
                ast.ArrayAccess(array=ast.Field(chain=[str(name)]))
                | ast.TupleAccess(tuple=ast.Field(chain=[str(name)]))
            ):
                self._graph.container_writes.append(self._local(name))
            case ast.Field(chain=[str(name), _]):
                self._graph.container_writes.append(self._local(name))
            case _:
                self._graph.container_writes.append(None)

    # An input can hold a closure that calls an async function, and code can swap a local function's upvalues, so any
    # call that does not name a builtin could reach one. A lambda literal callback is safe because its body is visited.
    def visit_expr_call(self, node: ast.ExprCall) -> None:
        super().visit_expr_call(node)
        self._sends()

    # The compiler runs every placeholder of an inline query, even in `SAMPLE`, and a function has no use for Hog SQL.
    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        super().visit_join_expr(node)
        self.visit(node.sample)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self._sends()
        super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self._sends()
        super().visit_select_set_query(node)

    # A tag calls the local of its name, including compiler temporaries such as `__expr__`, so any tag counts.
    def visit_hogqlx_tag(self, node: ast.HogQLXTag) -> None:
        super().visit_hogqlx_tag(node)
        if (binding := self._local(node.kind)) is not None:
            binding.rebound = True
        self._sends()

    def visit_call(self, node: ast.Call) -> None:
        super().visit_call(node)
        # The compiler declares locals this walk does not track, such as `__H_expr_H__` for the value a `for in` loop
        # reads, so a call to a name it reserves can run whatever that value holds.
        if node.name.startswith("__"):
            self._sends()
            return
        if (callee := self._local(node.name)) is not None:
            self.calls_out = True
            self._graph.calls.append(callee)
            if node.params is not None:
                # `f(params)(args)` calls whatever `f(params)` returns.
                self._sends()
            return
        if node.name == "fetch" and node.params is None and (url := _literal_string(node.args[:1])) is not None:
            self._sends(url)
            if len(node.args) > 1:
                self._check_json_body(node.args[1])
        elif node.params is not None or node.name not in _BUILTIN_FUNCTIONS or node.name in OUTBOUND_FUNCTIONS:
            self._sends()
        if node.name in _CALLBACK_FUNCTIONS and node.args and not isinstance(node.args[0], ast.Lambda):
            self._sends()
        if node.name in INTERNAL_FUNCTIONS:
            self.matched.add(Rule.INTERNAL_FUNCTION)
        elif node.name == "range" and _hog_range_size(node.args) > MAX_RANGE_SIZE:
            self.matched.add(Rule.HUGE_RANGE)
        elif node.name == "replaceAll" and _replaces_empty_string(node.args):
            self.matched.add(Rule.REPLACE_AMPLIFICATION)

    def _check_json_body(self, options: ast.Expr) -> None:
        """`fetch` sends a string body as it is, and a dict as JSON. Options count as JSON when they are a dict literal
        whose body, if any, is a dict literal or a local declared as one."""
        if not isinstance(options, ast.Dict):
            self._raw_body = True
            return
        for key, value in options.items:
            name = _literal_string([key])
            if name is None:
                self._raw_body = True
            elif name == "body" and not isinstance(value, ast.Dict):
                match value:
                    case ast.Field(chain=[str(local)]) if (binding := self._local(local)) is not None:
                        self._body_locals.append(binding)
                    case _:
                        self._raw_body = True

    def visit_field(self, node: ast.Field) -> None:
        # `let run := postHogCreateTask` followed by `run()` reaches the same handler as a direct call.
        super().visit_field(node)
        if (binding := self._local(str(node.chain[0]))) is not None:
            binding.rebound = True
            return
        if len(node.chain) != 1:
            return
        name = str(node.chain[0])
        self.calls_out |= name in OUTBOUND_FUNCTIONS
        self._other_call |= name in OUTBOUND_FUNCTIONS
        if name in INTERNAL_FUNCTIONS:
            self.matched.add(Rule.INTERNAL_FUNCTION)


def _literal_string(args: list[ast.Expr]) -> str | None:
    match args:
        case [ast.Constant(value=str(value))]:
            return value
    return None


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
    for tag in _liquid_tags(_decode_liquid_tags(template)):
        if any(liquid_range.length > MAX_RANGE_SIZE for liquid_range in _liquid_ranges(tag)):
            return True
    return False


@frozen
class _LiquidRange:
    low: float
    high: float

    @property
    def length(self) -> float:
        # LiquidJS adds 1 to `low` while the value stays below `high + 1`. Past 2**53 the addition no longer changes a
        # float, so the loop never ends.
        if math.isfinite(self.low) and self.low + 1 == self.low and self.low < self.high + 1:
            return math.inf
        return self.high - self.low + 1


def _liquid_ranges(tag: str) -> Iterator[_LiquidRange]:
    """The bounds of each range literal in a tag, skipping quoted strings. An unterminated string ends the scan,
    because LiquidJS cannot parse the tag, and that keeps a failed string from being scanned again."""
    position = 0
    while (stop := _LIQUID_STRING_OR_PAREN.search(tag, position)) is not None:
        if stop.group() == "(":
            literal = _LIQUID_RANGE.match(tag, stop.start())
            position = stop.end() if literal is None else literal.end()
            if literal is not None:
                yield _LiquidRange(low=_liquid_number(literal.group(1)), high=_liquid_number(literal.group(2)))
            continue
        string = _LIQUID_STRING.match(tag, stop.start())
        if string is None:
            return
        position = string.end()


def _decode_liquid_tags(template: str) -> str:
    """A port of `decodeLiquidTags` in `nodejs/src/cdp/utils/liquid.ts`, which runs before LiquidJS parses."""
    out: list[str] = []
    cursor = 0
    exhausted: set[str] = set()
    while (start := template.find("{", cursor)) != -1:
        closer = _DECODED_TAG_CLOSERS.get(template[start + 1 : start + 2])
        end = template.find(closer, start + 2) if closer is not None and closer not in exhausted else -1
        if end == -1:
            if closer is not None:
                exhausted.add(closer)
            out.append(template[cursor : start + 1])
            cursor = start + 1
            continue
        out.append(template[cursor:start] + _decode_encoded_spaces(_decode_entities(template[start : end + 2])))
        cursor = end + 2
    out.append(template[cursor:])
    return "".join(out)


def _decode_entities(tag: str) -> str:
    for entity, char in _DECODED_ENTITIES:
        tag = tag.replace(entity, char)
    return tag


def _decode_encoded_spaces(tag: str) -> str:
    """Every `%20` outside a quoted string becomes a space."""
    if "%20" not in tag:
        return tag
    out: list[str] = []
    position = 0
    while (stop := _QUOTE_OR_ENCODED_SPACE.search(tag, position)) is not None:
        out.append(tag[position : stop.start()])
        if stop.group() == "%20":
            out.append(" ")
            position = stop.end()
            continue
        string = _LIQUID_STRING.match(tag, stop.start())
        string_end = len(tag) if string is None else string.end()
        out.append(tag[stop.start() : string_end])
        position = string_end
    out.append(tag[position:])
    return "".join(out)


@frozen
class _LiquidTag:
    inside: str
    name: str
    is_output: bool


def _liquid_tags(template: str) -> Iterator[str]:
    """The inside of each output and logic tag that LiquidJS evaluates, in document order. Comments and raw blocks
    are left out."""
    in_comment = False
    for tag in _liquid_tokens(template):
        if in_comment:
            # A comment block reads its body as tokens and ends at the first logic tag named `endcomment`, so an end
            # tag in a quoted string or in the arguments of another tag does not end it.
            in_comment = tag.is_output or tag.name != "endcomment"
        elif not tag.is_output and tag.name == "comment":
            in_comment = True
        elif tag.name == "liquid":
            yield from _liquid_block_statements(tag.inside)
        elif tag.name != "#":
            yield tag.inside


def _liquid_tokens(template: str) -> Iterator[_LiquidTag]:
    """Each output and logic tag as the LiquidJS tokenizer reads it, in document order, without the inside of raw
    blocks. A template that LiquidJS cannot tokenize ends the scan, because none of it renders."""
    position = 0
    while (opener := _LIQUID_OPENER.search(template, position)) is not None:
        is_output = opener.group() == "{{"
        end = _output_tag_end(template, opener.end()) if is_output else template.find("%}", opener.end())
        if end == -1:
            return
        inside = template[opener.end() : end]
        position = end + 2
        name = _liquid_tag_name(inside.removeprefix("-").removesuffix("-"))
        if not is_output and name == "raw":
            position = _raw_block_end(template, position)
            if position == -1:
                return
            continue
        yield _LiquidTag(inside=inside, name=name, is_output=is_output)


def _raw_block_end(template: str, position: int) -> int:
    """Where the raw block whose text starts at `position` ends, after its `endraw` tag, or -1. A port of
    `readEndrawOrRawContent` in LiquidJS, where an `endraw` that meets another `{%` before its `%}` gives way to it."""
    candidate = template.find("{%", position)
    while candidate != -1:
        end_tag = _LIQUID_RAW_END.match(template, candidate)
        if end_tag is None:
            candidate = template.find("{%", candidate + 2)
            continue
        delimiter = _LIQUID_DELIMITER.search(template, end_tag.end())
        if delimiter is None:
            return -1
        if delimiter.group() == "%}":
            return delimiter.end()
        candidate = delimiter.start()
    return -1


def _liquid_tag_name(tag: str) -> str:
    """The tag name as LiquidJS's `readTagName` reads it."""
    match = _LIQUID_TAG_NAME.match(tag)
    return "" if match is None else match.group(1)


def _liquid_block_statements(tag: str) -> Iterator[str]:
    """Each statement of a `{% liquid %}` block is one line. Comment lines and the inside of comment and raw blocks
    are left out."""
    block_end: str | None = None
    # LiquidJS splits statements at `\n` only, while `splitlines` also splits at `\r` and Unicode separators.
    for line in tag.split("\n"):
        name = _liquid_tag_name(_LIQUID_STATEMENT_TRIM.sub("", line, count=1))
        if block_end is not None:
            block_end = None if name == block_end else block_end
        elif name in _LIQUID_TEXT_BLOCKS:
            block_end = f"end{name}"
        elif name != "#":
            yield line


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
    return _js_number(_liquid_string_value(bound) if bound[0] in "'\"" else bound)


def _liquid_string_value(literal: str) -> str:
    """The value of a quoted string, with escapes decoded as LiquidJS's `parseStringLiteral` decodes them."""
    return _LIQUID_STRING_ESCAPE.sub(_decoded_escape, literal[1:-1])


def _decoded_escape(escape: re.Match[str]) -> str:
    hex_digits, octal_digits, char = escape.groups()
    if hex_digits is not None:
        return chr(int(hex_digits, 16)) if hex_digits else "\0"
    if octal_digits is not None:
        return chr(int(octal_digits, 8))
    return _LIQUID_ESCAPED_CHARS.get(char, char)


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


def _all_inputs(content: HogFunctionContent, keys: frozenset[str] | None = None) -> Iterator[JsonValue]:
    """Every input value, or only the values under `keys`. A mapping's inputs share keys with the function's,
    because the runtime merges them into one `inputs` global."""
    for inputs in (
        content.inputs,
        *(mapping.get("inputs") for mapping in content.mappings if isinstance(mapping, dict)),
    ):
        if isinstance(inputs, dict):
            yield from (value for key, value in inputs.items() if keys is None or key in keys)


def _template_url_inputs(content: HogFunctionContent) -> frozenset[str] | None:
    """The input keys that can reach the URL of a `fetch` call in unedited template code, or None when any input
    could. A stock template can put an input only in a request body, such as a Slack button link, so a local URL
    there is message content and never a request target. Edited and custom code is never traced, because the tracer
    does not follow every path a value can take, such as a dict changed through a second name, and a customer can
    write code that takes one."""
    if content.type != "destination" or content.code_modified_from_template is not False:
        return None
    if (content.template_id or "").startswith(_NON_HOG_EXECUTOR_PREFIXES):
        return None
    try:
        keys = _url_inputs_of(_parse_code(content.hog))
    except Exception:
        return None
    # A templated input can read the inputs rendered before it, and Hog and Liquid can both reach `inputs` without
    # spelling the name, so any template in a URL input could carry the host of any other input.
    if any("{" in text for text in _strings(list(_all_inputs(content, keys)))):
        return None
    return keys


# The CDP worker runs a destination with one of these template ID prefixes in TypeScript, not as its Hog code, so the
# stored code says nothing about where it sends a request. Kept in sync with `isNativeHogFunction`,
# `isSegmentPluginHogFunction` and `isLegacyPluginHogFunction` in `nodejs/src/cdp/utils.ts`.
_NON_HOG_EXECUTOR_PREFIXES = ("native-", "segment-", "plugin-")

# The globals a destination reads besides `inputs`. None of them holds an input value.
_HOG_GLOBALS = frozenset({"event", "person", "project", "source", "groups", "context", "variables"})


class _Untraceable(Exception):
    pass


def _url_inputs_of(program: ast.AST) -> frozenset[str]:
    code = _RequestCodeVisitor()
    code.visit(program)
    tracer = _UrlInputTracer(code)
    for url in code.fetch_urls:
        tracer.visit(url)
    return frozenset(tracer.keys)


class _RequestCodeVisitor(TraversingVisitor):
    """Collects the first argument of each `fetch` call and every value each variable name is given, ignoring
    scope, so a name stands for the union of all the values that any variable of that name can hold. Raises
    `_Untraceable` when a request target cannot be found this way: a `fetch` inside a function or lambda, where
    the URL can come from a parameter, or `fetch` passed around as a value."""

    def __init__(self) -> None:
        super().__init__()
        self.fetch_urls: list[ast.Expr] = []
        self.values: dict[str, list[ast.Expr]] = {}
        self.functions: set[str] = set()
        self._function_depth = 0

    def _assign(self, name: str, value: ast.Expr) -> None:
        self.values.setdefault(name, []).append(value)

    def visit_function(self, node: ast.Function) -> None:
        self.functions.add(node.name)
        self._function_depth += 1
        try:
            super().visit_function(node)
        finally:
            self._function_depth -= 1

    def visit_lambda(self, node: ast.Lambda) -> None:
        self._function_depth += 1
        try:
            super().visit_lambda(node)
        finally:
            self._function_depth -= 1

    def visit_variable_declaration(self, node: ast.VariableDeclaration) -> None:
        super().visit_variable_declaration(node)
        if node.expr is not None:
            self._assign(node.name, node.expr)

    def visit_variable_assignment(self, node: ast.VariableAssignment) -> None:
        super().visit_variable_assignment(node)
        # `body['url'] := inputs.url` changes what `body` holds, so the value counts for the base name.
        name = _base_name(node.left)
        if name is None:
            raise _Untraceable
        self._assign(name, node.right)

    def visit_for_in_statement(self, node: ast.ForInStatement) -> None:
        super().visit_for_in_statement(node)
        for name in (node.valueVar, node.keyVar):
            if name:
                self._assign(name, node.expr)

    def visit_call(self, node: ast.Call) -> None:
        super().visit_call(node)
        if node.name != "fetch":
            return
        if self._function_depth:
            raise _Untraceable
        if node.args:
            self.fetch_urls.append(node.args[0])

    def visit_field(self, node: ast.Field) -> None:
        super().visit_field(node)
        if node.chain[0] == "fetch":
            raise _Untraceable


class _UrlInputTracer(TraversingVisitor):
    """Collects the input keys that an expression can read, following each variable to every value it is given.
    Raises `_Untraceable` for anything that could read an input it cannot name: all of `inputs`, an input key
    computed at runtime, a name that is neither a variable nor a global, or a call to a function the code declares."""

    def __init__(self, code: _RequestCodeVisitor) -> None:
        super().__init__()
        self.keys: set[str] = set()
        self._code = code
        self._followed: set[str] = set()

    def visit_array_access(self, node: ast.ArrayAccess) -> None:
        if not _is_all_inputs(node.array):
            super().visit_array_access(node)
        elif isinstance(node.property, ast.Constant) and isinstance(node.property.value, str):
            self.keys.add(node.property.value)
        else:
            raise _Untraceable

    def visit_field(self, node: ast.Field) -> None:
        name, *path = node.chain
        if name == "inputs":
            if not path or not isinstance(path[0], str):
                raise _Untraceable
            self.keys.add(path[0])
        elif name in self._code.values:
            if name not in self._followed:
                self._followed.add(name)
                for value in self._code.values[name]:
                    self.visit(value)
        elif name not in _HOG_GLOBALS:
            raise _Untraceable

    def visit_call(self, node: ast.Call) -> None:
        if node.name in self._code.functions or node.name in self._code.values:
            raise _Untraceable
        super().visit_call(node)


def _is_all_inputs(node: ast.Expr) -> bool:
    return isinstance(node, ast.Field) and node.chain == ["inputs"]


def _base_name(node: ast.Expr) -> str | None:
    while isinstance(node, ast.ArrayAccess | ast.TupleAccess):
        node = node.array if isinstance(node, ast.ArrayAccess) else node.tuple
    if isinstance(node, ast.Field) and isinstance(node.chain[0], str):
        return node.chain[0]
    return None


def _request_targets(content: HogFunctionContent, url_inputs: frozenset[str] | None) -> Iterator[str]:
    """The strings a destination sends a request to. A transformation runs without network access."""
    if content.type != "destination":
        return
    yield from _strings(list(_all_inputs(content, url_inputs)))
    yield from (literal.group(1) or literal.group(2) or "" for literal in _FETCH_LITERAL.finditer(content.hog))


def _texts(content: HogFunctionContent, input_keys: frozenset[str] | None = None) -> Iterator[str]:
    """The strings that run or reach a request. Filters are left out, because they only match events, and an
    event filter on a local `$current_url` is ordinary."""
    yield content.hog
    yield from _strings(list(_all_inputs(content, input_keys)))
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
    return _in_domains(canonicalize_host(host), _REQUEST_CATCHER_DOMAINS)


def _is_security_callback(host: str) -> bool:
    canonical = canonicalize_host(host)
    return (
        _in_domains(canonical, _SECURITY_CALLBACK_DOMAINS)
        or matched_oob_domain(canonical) is not None
        or _SECURITY_CALLBACK_TOOL_NAME.search(canonical) is not None
    )


def _in_domains(canonical_host: str, domains: frozenset[str]) -> bool:
    return any(canonical_host == domain or canonical_host.endswith(f".{domain}") for domain in domains)
