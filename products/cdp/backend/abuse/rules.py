"""Exact rules that flag a hog function beside Jev's answers, so a probe is caught even when the model call fails.

Pure: no database, no DNS lookup, no network.
"""

import re
import json
import math
import ipaddress
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from posthog.hogql import ast
from posthog.hogql.parser import CacheOrigin, parse_program, parse_string_template
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.schema_enums import ParserMode
from posthog.security.oob_domains import matched_oob_domain
from posthog.security.url_validation import canonicalize_host, internal_host_name

from products.cdp.backend.abuse.classifier import MAX_STATE_CHARS, HogFunctionContent
from products.ml_inference.backend.facade.contracts import JsonValue

from common.hogvm.python.stl import STL
from common.hogvm.python.stl.bytecode import BYTECODE_STL


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
# The compiler declares locals of its own, such as `e` and `type` in a catch block, so a call is safe only when it names
# a standard library function.
_BUILTIN_FUNCTIONS = frozenset(STL) | frozenset(BYTECODE_STL)

# Source that names none of these cannot match a rule that reads parsed Hog, so it is not parsed.
_HOG_RULE_NAMES = re.compile("|".join(sorted(INTERNAL_FUNCTIONS | {"range", "replaceAll"})))

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


class _HogCodeVisitor(TraversingVisitor):
    """Tracks the names in scope in source order, as the bytecode compiler does, because a call to a declared name
    runs the local and never reaches the standard library or the async function registry."""

    def __init__(self) -> None:
        super().__init__()
        self.matched: set[Rule] = set()
        self.calls_out = False
        self._scopes: list[set[str]] = [set()]

    def _is_local(self, name: str) -> bool:
        return any(name in scope for scope in self._scopes)

    @contextmanager
    def _scope(self, names: Iterable[str] = ()) -> Iterator[None]:
        self._scopes.append(set(names))
        try:
            yield
        finally:
            self._scopes.pop()

    def visit_block(self, node: ast.Block) -> None:
        with self._scope():
            super().visit_block(node)

    def visit_function(self, node: ast.Function) -> None:
        self._scopes[-1].add(node.name)
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
        for name, _error_type, handler in node.catches:
            with self._scope([name] if name else []):
                self.visit(handler)
        self.visit(node.finally_stmt)

    def visit_variable_declaration(self, node: ast.VariableDeclaration) -> None:
        super().visit_variable_declaration(node)
        self._scopes[-1].add(node.name)

    # An input can hold a closure that calls an async function, and code can swap a local function's upvalues, so any
    # call that does not name a builtin could reach one. A lambda literal callback is safe because its body is visited.
    def visit_expr_call(self, node: ast.ExprCall) -> None:
        super().visit_expr_call(node)
        self.calls_out = True

    def visit_hogqlx_tag(self, node: ast.HogQLXTag) -> None:
        super().visit_hogqlx_tag(node)
        self.calls_out |= self._is_local(node.kind)

    def visit_call(self, node: ast.Call) -> None:
        super().visit_call(node)
        if self._is_local(node.name):
            self.calls_out = True
            return
        self.calls_out |= (
            node.params is not None or node.name not in _BUILTIN_FUNCTIONS or node.name in OUTBOUND_FUNCTIONS
        )
        if node.name in _CALLBACK_FUNCTIONS and node.args and not isinstance(node.args[0], ast.Lambda):
            self.calls_out = True
        if node.name in INTERNAL_FUNCTIONS:
            self.matched.add(Rule.INTERNAL_FUNCTION)
        elif node.name == "range" and _hog_range_size(node.args) > MAX_RANGE_SIZE:
            self.matched.add(Rule.HUGE_RANGE)
        elif node.name == "replaceAll" and _replaces_empty_string(node.args):
            self.matched.add(Rule.REPLACE_AMPLIFICATION)

    def visit_field(self, node: ast.Field) -> None:
        # `let run := postHogCreateTask` followed by `run()` reaches the same handler as a direct call.
        super().visit_field(node)
        if len(node.chain) != 1:
            return
        name = str(node.chain[0])
        if self._is_local(name):
            return
        self.calls_out |= name in OUTBOUND_FUNCTIONS
        if name in INTERNAL_FUNCTIONS:
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
