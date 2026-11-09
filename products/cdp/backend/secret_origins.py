"""Which origins a hog function's code can send each of its secret inputs to.

The analysis is flow-insensitive and conservative. Every assignment to a name counts wherever it
appears, and a secret whose destination cannot be pinned to known origins is `UNBOUND`.
"""

import re
import dataclasses
from collections.abc import Iterable, Iterator
from enum import Enum
from typing import Any, Literal

from prometheus_client import Counter

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_program, parse_string_template

from posthog.dataclasses import frozen


class Unbound(Enum):
    UNBOUND = "*"


UNBOUND = Unbound.UNBOUND
SecretOrigins = frozenset[str] | Unbound

# A possible string value, as the text it is known to start with and whether that text is all of it.
_Prefix = tuple[str, bool]
_Values = frozenset[_Prefix]
_UNKNOWN: _Values = frozenset({("", False)})
_MAX_VALUES = 32
# Only the start of a value can hold its origin, so text past this length is dropped instead of tracked.
_MAX_TEXT = 2048
_MAX_ITERATIONS = 64
# Expression evaluations one analysis may make. The budget sits far above what real templates need, so
# only a source written to be slow runs out, and the analysis then treats it as one it cannot pin down.
_MAX_EVALUATIONS = 25_000
_SCHEME = re.compile(r"(https?)://", re.IGNORECASE)
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_UNSAFE_AUTHORITY = re.compile(r"[@\\%\s\x00-\x1f\x7f]")
_NUMERIC_LABEL = re.compile(r"^(\d+|0x[0-9a-f]*)$")
_BY_NAME_OPTIONS = frozenset({"secret_headers_input", "standard_webhooks", "aws_sigv4"})
# The worker copies a dict into a JS object key by key, so these keys can set its prototype, and option reads
# such as `secret_headers_input` then find a value no key of the dict shows.
_PROTOTYPE_KEYS = frozenset({"__proto__", "constructor", "prototype"})
# Headers that route a request to a host other than the one in its URL, as on a CDN that serves many hosts.
_HOST_HEADERS = frozenset({"host", ":authority"})
_VALUE_CALLS = frozenset({"concat", "coalesce", "ifNull", "if"})
# Standard library calls that never log, send or quote their arguments, not even in an error. Any other
# call, including a worker function added later, can carry its arguments out of the function.
_PURE_CALLS = frozenset(
    {
        "arrayPushBack",
        "base64Encode",
        "empty",
        "encodeURLComponent",
        "equals",
        "jsonStringify",
        "length",
        "lower",
        "notEmpty",
        "notEquals",
        "replaceAll",
        "substring",
        "toString",
        "trim",
        "upper",
    }
)
# One-way digests. Their result cannot reveal the secret, but sending it elsewhere still moves what
# the secret signs.
_DIGEST_CALLS = frozenset(
    {"md5Hex", "sha1Hex", "sha256", "sha256Hex", "sha1HmacChainHex", "sha256HmacChain", "sha256HmacChainHex"}
)
# Calls whose result reveals only part of the secret, or a few bits of it. Code can pick the part, so a
# digest of the result can be reversed by trying every value it can have.
_PIECE_CALLS = frozenset({"substring", "replaceAll", "length", "empty", "notEmpty", "equals", "notEquals"})
_PIECE_EXPRS = (ast.CompareOperation, ast.BetweenExpr, ast.Not, ast.And, ast.Or)
# The worker prints an object shaped like a query AST with its HogQL printer when it converts it to text,
# and the printer quotes an unknown node type in the error it throws.
_PRINTING_CALLS = frozenset({"concat", "toString"})
# Calls that feed their lambda only elements of their other arguments, unlike `arrayReduce` or template code.
_ELEMENT_CALLBACK_CALLS = frozenset({"arrayMap", "arrayFilter", "arrayExists", "arrayCount"})
# Code that declares one of these names replaces the meaning the analysis gives it.
_INTERPRETED_NAMES = (
    frozenset({"inputs", "fetch"}) | _VALUE_CALLS | _PURE_CALLS | _DIGEST_CALLS | _ELEMENT_CALLBACK_CALLS
)
_SAFE_CALLS = _VALUE_CALLS | _PURE_CALLS | _DIGEST_CALLS
_SCALAR_CALLS = (_PURE_CALLS - {"arrayPushBack"}) | _DIGEST_CALLS | {"concat"}
_FRESH_CONTAINERS = (ast.Dict, ast.Array, ast.Tuple)
_COMPARISONS = (ast.CompareOperation, ast.BetweenExpr)
# A regex the worker cannot compile fails with the pattern in the error.
_REGEX_OPS = frozenset(
    {
        ast.CompareOperationOp.Regex,
        ast.CompareOperationOp.IRegex,
        ast.CompareOperationOp.NotRegex,
        ast.CompareOperationOp.NotIRegex,
    }
)

UnanalyzableReason = Literal["unsupported_code", "input_cycle", "iterations", "budget", "unparseable", "too_deep"]
SECRET_ORIGINS_UNANALYZABLE_COUNTER = Counter(
    "posthog_cdp_secret_origins_unanalyzable_total",
    "Secret origin analyses that left every secret unbound, by why the code could not be analyzed.",
    labelnames=["reason"],
)


@frozen
class _Derived:
    """A value computed from the secret `key` that does not hold it: a digest of it, or the response to
    a request that carried it."""

    key: str


@frozen
class _Piece:
    """A value computed from part of the secret `key`, or from a few bits of it. It counts as the secret
    itself, and a digest of it does too."""

    key: str


_Taint = frozenset[str | _Derived | _Piece]


@frozen
class _ContainerSources:
    """The expressions a dict can come from, the member writes that change it as (keys, value), and the
    names already followed, which stop a cycle."""

    sources: list[ast.Expr]
    writes: list[tuple[list[str | None], ast.Expr]]
    seen: frozenset[str]


def _derived(taint: _Taint) -> _Taint:
    return frozenset(_Derived(key=item) if isinstance(item, str) else item for item in taint)


def _pieces(taint: _Taint) -> _Taint:
    return frozenset(_Piece(key=item) if isinstance(item, str) else item for item in taint)


def _held(taint: _Taint) -> frozenset[str]:
    return frozenset(item.key if isinstance(item, _Piece) else item for item in taint if not isinstance(item, _Derived))


def _reached(taint: _Taint) -> frozenset[str]:
    return frozenset(item if isinstance(item, str) else item.key for item in taint)


class _CannotAnalyze(Exception):
    def __init__(self, reason: UnanalyzableReason) -> None:
        super().__init__(reason)
        self.reason = reason


@frozen
class SecretOriginsAnalysis:
    origins: dict[str, SecretOrigins]
    unanalyzable: UnanalyzableReason | None = None


def analyze_secret_origins(
    hog: str, inputs: dict[str, Any], mapping_input_sets: list[dict[str, Any]], secret_keys: set[str]
) -> SecretOriginsAnalysis:
    reason: UnanalyzableReason
    try:
        return SecretOriginsAnalysis(origins=_Analysis(hog, [inputs, *mapping_input_sets], secret_keys).run())
    except _CannotAnalyze as error:
        reason = error.reason
    except BaseHogQLError:
        reason = "unparseable"
    except RecursionError:
        reason = "too_deep"
    SECRET_ORIGINS_UNANALYZABLE_COUNTER.labels(reason=reason).inc()
    return SecretOriginsAnalysis(origins=dict.fromkeys(secret_keys, UNBOUND), unanalyzable=reason)


def secret_origins(
    hog: str, inputs: dict[str, Any], mapping_input_sets: list[dict[str, Any]], secret_keys: set[str]
) -> dict[str, SecretOrigins]:
    return analyze_secret_origins(hog, inputs, mapping_input_sets, secret_keys).origins


def resolved_inputs(inputs: Any, inputs_schema: Any) -> dict[str, Any]:
    """The inputs with what their schema changes in how the worker resolves them. A schema can turn hog
    templating off, which leaves the value as written, and the worker turns the text of a boolean input
    into a boolean."""
    schemas = {schema.get("key"): schema for schema in inputs_schema or [] if isinstance(schema, dict)}
    resolved: dict[str, Any] = {}
    for key, item in (inputs or {}).items():
        schema = schemas.get(key) or {}
        if isinstance(item, dict) and schema.get("templating") is False and item.get("templating") != "liquid":
            item = {**item, "templating": False}
        if isinstance(item, dict) and schema.get("type") == "boolean":
            item = {**item, "schema_type": "boolean"}
        resolved[key] = item
    return resolved


def mapping_inputs(mappings: Any) -> list[dict[str, Any]]:
    return [
        resolved_inputs(mapping.get("inputs"), mapping.get("inputs_schema"))
        for mapping in mappings or []
        if isinstance(mapping, dict)
    ]


def stored_origins(origins: SecretOrigins) -> str | list[str]:
    return UNBOUND.value if origins is UNBOUND else sorted(origins)


def parse_stored_origins(stored: Any) -> SecretOrigins | None:
    if stored == UNBOUND.value:
        return UNBOUND
    if isinstance(stored, list) and all(isinstance(origin, str) for origin in stored):
        return frozenset(stored)
    return None


def url_origin(prefix: str, complete: bool) -> str | None:
    scheme = _SCHEME.match(prefix)
    if not scheme:
        return None
    rest = prefix[scheme.end() :]
    end = min((index for index in (rest.find(c) for c in "/?#") if index >= 0), default=-1)
    if end < 0 and not complete:
        return None
    authority = rest if end < 0 else rest[:end]
    # Python's IDNA codec and the WHATWG URL parser map some non-ASCII hosts differently.
    if not authority or not authority.isascii() or _UNSAFE_AUTHORITY.search(authority):
        return None
    host, _, port = authority.lower().rpartition(":") if ":" in authority else (authority.lower(), "", "")
    if port and not _is_canonical_port(port):
        return None
    host = host.rstrip(".")
    if not host or not _is_canonical_host(host):
        return None
    scheme_name = scheme.group(1).lower()
    origin = f"{scheme_name}://{host}"
    return origin if not port or port == _DEFAULT_PORTS[scheme_name] else f"{origin}:{port}"


def _is_canonical_port(port: str) -> bool:
    return len(port) <= 5 and port.isdigit() and not port.startswith("0") and int(port) <= 65535


# The worker's WHATWG parser rewrites IPv6 and short or hex IPv4 hosts, so only a dotted quad keeps its text.
def _is_canonical_host(host: str) -> bool:
    if host.startswith("["):
        return False
    labels = host.split(".")
    if not _NUMERIC_LABEL.match(labels[-1]):
        return True
    return len(labels) == 4 and all(
        len(label) <= 3 and label.isdigit() and str(int(label)) == label and int(label) <= 255 for label in labels
    )


def _normalize(values: _Values) -> _Values:
    return _UNKNOWN if ("", False) in values or len(values) > _MAX_VALUES else values


def _concat(parts: list[_Values]) -> _Values:
    joined: _Values = frozenset({("", True)})
    for part in parts:
        joined = _normalize(
            frozenset(
                _append(text, more, more_complete) if complete else (text, False)
                for text, complete in joined
                for more, more_complete in (part if complete else [("", False)])
            )
        )
    return joined


def _append(text: str, more: str, more_complete: bool) -> _Prefix:
    room = max(0, _MAX_TEXT - len(text))
    return text + more[:room], more_complete and len(more) <= room


def _children(node: Any) -> Iterator[ast.AST]:
    for field in dataclasses.fields(node):
        yield from _flatten(getattr(node, field.name))


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in _children(node):
        yield from _walk(child)


def _flatten(value: Any) -> Iterator[ast.AST]:
    if isinstance(value, ast.AST):
        yield value
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _flatten(item)


def _assignment_base(left: ast.Expr) -> tuple[str, int]:
    """The assigned name and how many member accesses lead from it to the assigned slot."""
    depth = 0
    while isinstance(left, ast.ArrayAccess | ast.TupleAccess):
        left = left.array if isinstance(left, ast.ArrayAccess) else left.tuple
        depth += 1
    if not isinstance(left, ast.Field) or not isinstance(left.chain[0], str):
        raise _CannotAnalyze("unsupported_code")
    return left.chain[0], depth + len(left.chain) - 1


def _header_entry_hosts(name: Any, value: ast.Expr) -> frozenset[str] | None:
    if not isinstance(name, str):
        return None
    if name.lower() not in _HOST_HEADERS:
        return frozenset()
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return frozenset({value.value})
    return None


def _is_constant(node: ast.Expr, value: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def _assignment_target(left: ast.Expr) -> ast.Expr:
    while isinstance(left, ast.ArrayAccess | ast.TupleAccess):
        left = left.array if isinstance(left, ast.ArrayAccess) else left.tuple
    return left


def _assigned_keys(left: ast.Expr) -> list[str | None]:
    accessed: list[str | None] = []
    while isinstance(left, ast.ArrayAccess | ast.TupleAccess):
        if isinstance(left, ast.ArrayAccess):
            key = left.property
            accessed.append(str(key.value) if isinstance(key, ast.Constant) and key.value is not None else None)
            left = left.array
        else:
            accessed.append(str(left.index))
            left = left.tuple
    chain = [str(part) for part in left.chain[1:]] if isinstance(left, ast.Field) else []
    return chain + accessed[::-1]


def _computed_keys(left: ast.Expr) -> list[ast.Expr]:
    keys = []
    while isinstance(left, ast.ArrayAccess | ast.TupleAccess):
        if isinstance(left, ast.ArrayAccess) and not isinstance(left.property, ast.Constant):
            keys.append(left.property)
        left = left.array if isinstance(left, ast.ArrayAccess) else left.tuple
    return keys


class _Analysis:
    def __init__(self, hog: str, input_sets: list[dict[str, Any]], secret_keys: set[str]) -> None:
        self.secret_keys = frozenset(secret_keys)
        self.evaluations_left = _MAX_EVALUATIONS
        self.values: dict[str, _Values] = {}
        self.taints: dict[str, _Taint] = {}
        self.return_values: dict[str, _Values] = {}
        self.return_taints: dict[str, _Taint] = {}
        self.declarations: set[str] = set()
        self.assignments: list[tuple[str, ast.Expr]] = []
        self.member_assignments: list[tuple[str, int, ast.Expr]] = []
        self.member_writes: list[tuple[str, list[str | None], ast.Expr]] = []
        self.fresh_containers: set[str] = set()
        # Nodes that read a dict only to send it, or to write into it, so the read hands it to no other code.
        self.sending_reads: set[int] = set()
        # Names and `inputs.<key>` whose dict other code can reach, with "inputs" for every input.
        self.escaped: set[str] = set()
        self.host_write_bases: set[str] = set()
        self.shared_assignments: list[ast.Expr] = []
        self.reads_all_inputs = False
        # Names bound by loops, lambdas and catch clauses, with the expressions that feed them, or
        # None when anything could.
        self.fed_names: list[tuple[str, list[ast.Expr] | None]] = []
        self.functions: dict[str, list[str]] = {}
        self.returns: list[tuple[str, ast.Expr]] = []
        self.calls: list[ast.Call] = []
        self.comparisons: list[ast.CompareOperation | ast.BetweenExpr] = []
        # Declared names whose every value comes from their own assignments.
        self.assigned_only: set[str] = set()
        self.field_heads: set[str] = set()
        self.lambda_feeds: dict[int, list[ast.Expr]] = {}
        # Lambdas a declaration binds to a name, and the parameters of each with that name.
        self.lambda_names: dict[int, str] = {}
        # Each name a `fun` or a declared lambda binds, with whether a statement of the program itself
        # declares it and where.
        self.callee_declarations: dict[str, list[tuple[bool, int]]] = {}
        # Names declared without a value, which the VM sets to null.
        self.unset_names: list[str] = []
        self.named_lambda_args: list[tuple[str, str]] = []
        self.lambdas_only: set[str] = set()
        # Expressions whose value can leave the function other than through `fetch`.
        self.exits: list[ast.Expr] = []

        self.definitions: dict[str, list[dict]] = {}
        for input_set in input_sets:
            for key, item in (input_set or {}).items():
                if isinstance(item, dict) and "value" in item:
                    self.definitions.setdefault(key, []).append(item)
        self.inputs: dict[str, tuple[_Values, _Taint]] = {}
        for key in self.definitions:
            self._input(key, set())

        program = parse_program(hog)
        self.top_level = {id(statement) for statement in program.declarations}
        self._collect(program, None)
        feeds: dict[str, list[ast.Expr] | None] = {}
        for arg, name in self.named_lambda_args:
            self._spend_evaluation()
            if name not in feeds:
                feeds[name] = self._call_arguments(name)
            self.fed_names.append((arg, feeds[name]))
        bound_elsewhere = {name for name, _ in self.fed_names}
        bound_elsewhere |= {param for params in self.functions.values() for param in params}
        variables = {name for name, _ in self.assignments} | self.declarations | bound_elsewhere
        fresh = self._fresh_container_names() - bound_elsewhere
        self.fresh_containers = fresh
        self.host_write_bases = {
            base
            for base, keys, _ in self.member_writes
            if keys[-1] is None or keys[-1].lower() in _HOST_HEADERS or keys[-1] == "headers"
        }
        self.shared_assignments = [
            expr for base, depth, expr in self.member_assignments if depth > 1 or base not in fresh
        ]
        if self._rebinds_an_interpreted_name(variables) or self._hands_on_a_callee() or self._can_replace_inputs():
            raise _CannotAnalyze("unsupported_code")

        local = self.declarations | bound_elsewhere | set(self.functions)
        self.lambdas_only = self._lambda_only_names() - bound_elsewhere - set(self.functions)
        if self._calls_past_a_declaration():
            raise _CannotAnalyze("unsupported_code")
        self.exits += [expr for base, _, expr in self.member_assignments if base not in local]
        self.exits += [expr for name, expr in self.assignments if name not in local]
        self.assigned_only = self.declarations - bound_elsewhere - {base for base, _, _ in self.member_assignments}
        self.exits += self._compared_exits(self.comparisons)
        self.exits += self._printed_exits(self.calls)
        quiet = {"fetch", *_SAFE_CALLS, *self.functions, *self.lambdas_only}
        self.exits += [
            arg for call in self.calls if call.name not in quiet and not _calls_back_inline(call) for arg in call.args
        ]

    def _rebinds_an_interpreted_name(self, variables: set[str]) -> bool:
        functions = set(self.functions)
        return bool((variables | functions) & _INTERPRETED_NAMES or variables & functions)

    def _declare_callee(self, node: ast.Function | ast.VariableDeclaration) -> None:
        self.callee_declarations.setdefault(node.name, []).append((id(node) in self.top_level, node.start or 0))

    def _calls_past_a_declaration(self) -> bool:
        """Whether a call to the code's own function can reach a built-in of the same name. The analysis
        resolves the name wherever the function is declared, but the VM resolves it to the function only
        after a declaration that is a statement of the program itself. Elsewhere the call reaches the
        built-in, such as a `print` that writes the secret to the logs."""
        own = set(self.functions) | self.lambdas_only
        return any(
            not top_level or start > (call.start or 0)
            for call in self.calls
            if call.name in own
            for top_level, start in self.callee_declarations.get(call.name, [])
        )

    def _hands_on_a_callee(self) -> bool:
        """Whether code passes `fetch` or one of its own functions as a value, to be called where the
        analysis cannot see the arguments."""
        return bool(self.field_heads & {"fetch", *self.functions})

    def _can_replace_inputs(self) -> bool:
        """The analysis reads input values as configured, so code must not be able to replace them."""
        writes_inputs = any(base == "inputs" for base, _, _ in self.member_assignments)
        return writes_inputs or (self.reads_all_inputs and bool(self.shared_assignments))

    def _lambda_only_names(self) -> set[str]:
        assigned = {name for name, _ in self.assignments}
        return assigned - {name for name, expr in self.assignments if not isinstance(expr, ast.Lambda)}

    def _call_arguments(self, lambda_name: str) -> list[ast.Expr] | None:
        """Every argument of every call to a name that only declarations of lambdas bind, or None when the
        lambda can be reached another way. A name used as a value can hand the lambda to code that calls
        it with any argument."""
        params = {param for params in self.functions.values() for param in params}
        bound_otherwise = {name for name, _ in self.fed_names} | {arg for arg, _ in self.named_lambda_args} | params
        if lambda_name not in self._lambda_only_names() or lambda_name in (
            self.field_heads | bound_otherwise | set(self.functions)
        ):
            return None
        return [arg for call in self.calls if call.name == lambda_name for arg in call.args]

    def _fresh_container_names(self) -> set[str]:
        """Names only ever assigned a new dict, array or tuple. No other name reaches that object, so
        taint from a member assignment on it is carried by reads of the name."""
        stale = {name for name, expr in self.assignments if not isinstance(expr, _FRESH_CONTAINERS)}
        return {name for name, _ in self.assignments} - stale

    def _input(self, key: str, resolving: set[str]) -> tuple[_Values, _Taint]:
        if key in self.inputs:
            return self.inputs[key]
        if key in resolving:
            raise _CannotAnalyze("input_cycle")
        resolving.add(key)
        values: _Values = frozenset() if key in self.definitions else _UNKNOWN
        taint: _Taint = frozenset({key}) & self.secret_keys
        for item in self.definitions.get(key, []):
            item_values, item_taint = self._template(item["value"], item.get("templating"), resolving)
            values, taint = _normalize(values | item_values), taint | item_taint
            if item.get("schema_type") == "boolean":
                # The worker turns the text into true or false, which keeps a bit of any secret it read.
                values, taint = _UNKNOWN, _pieces(taint)
        self.inputs[key] = (values, taint)
        return self.inputs[key]

    def _template(self, value: Any, templating: Any, resolving: set[str]) -> tuple[_Values, _Taint]:
        if isinstance(value, dict | list):
            taint: _Taint = frozenset()
            for item in value.values() if isinstance(value, dict) else value:
                taint |= self._template(item, templating, resolving)[1]
            return _UNKNOWN, taint
        if not isinstance(value, str):
            return _UNKNOWN, frozenset()
        if templating is False:
            # The worker sends the value as written, so a template in it never runs.
            return frozenset({(value, True)}), frozenset()
        mentioned = frozenset(key for key in self.secret_keys if key in value)
        if templating == "liquid":
            dynamic = [index for index in (value.find("{{"), value.find("{%")) if index >= 0]
            if not dynamic:
                return frozenset({(value, True)}), mentioned
            # Liquid can reach every input without naming one, as in `{{ inputs | json }}`.
            return frozenset({(value[: min(dynamic)], False)}), self.secret_keys
        try:
            expr = parse_string_template(value)
        except BaseHogQLError:
            return _UNKNOWN, mentioned
        nodes = list(_walk(expr))
        if any(_is_unmodeled(node) for node in nodes):
            raise _CannotAnalyze("unsupported_code")
        for key in {key for node in nodes if (key := _input_key(node)) is not None}:
            self._input(key, resolving)
        self.exits += [
            arg for node in nodes if isinstance(node, ast.Call) and node.name not in _SAFE_CALLS for arg in node.args
        ]
        self.exits += self._compared_exits(node for node in nodes if isinstance(node, _COMPARISONS))
        self.exits += self._printed_exits(node for node in nodes if isinstance(node, ast.Call))
        return self._value(expr), self._taint(expr)

    def _compared_exits(self, comparisons: Iterable[ast.CompareOperation | ast.BetweenExpr]) -> list[ast.Expr]:
        """The worker reads an object shaped like a date as a date when it compares it, and its date
        library quotes an invalid field in the error. A regex it cannot compile is quoted the same way."""
        exits: list[ast.Expr] = []
        for node in comparisons:
            if isinstance(node, ast.BetweenExpr):
                exits += [side for side in (node.expr, node.low, node.high) if not self._scalar(side, frozenset())]
            elif node.op in _REGEX_OPS:
                exits += [node.left, node.right]
            else:
                exits += [side for side in (node.left, node.right) if not self._scalar(side, frozenset())]
        return exits

    def _printed_exits(self, calls: Iterable[ast.Call]) -> list[ast.Expr]:
        return [
            arg
            for call in calls
            if call.name in _PRINTING_CALLS
            for arg in call.args
            if not self._scalar(arg, frozenset())
        ]

    def _scalar(self, node: ast.Expr, seen: frozenset[str]) -> bool:
        """Whether `node` can only be a string, number, boolean or null. `seen` holds the names and
        inputs being resolved, which a cycle cannot make anything else."""
        self._spend_evaluation()
        if isinstance(node, ast.Constant | ast.CompareOperation | ast.And | ast.Or | ast.Not):
            return True
        if isinstance(node, ast.Call) and node.name in ("coalesce", "ifNull"):
            return all(self._scalar(arg, seen) for arg in node.args)
        if isinstance(node, ast.Call) and node.name == "if":
            return len(node.args) == 3 and all(self._scalar(arg, seen) for arg in node.args[1:])
        if isinstance(node, ast.Call):
            return node.name in _SCALAR_CALLS and node.name not in self.functions
        key = _input_key(node)
        if key is not None:
            return (not isinstance(node, ast.Field) or len(node.chain) == 2) and self._scalar_input(key, seen)
        if not isinstance(node, ast.Field) or len(node.chain) != 1:
            return False
        name = str(node.chain[0])
        if name in seen:
            return True
        if name in self.assigned_only:
            feeds: list[ast.Expr] | None = [expr for assigned, expr in self.assignments if assigned == name]
        else:
            feeds = self._parameter_feeds(name)
        return feeds is not None and all(self._scalar(expr, seen | {name}) for expr in feeds)

    def _parameter_feeds(self, name: str) -> list[ast.Expr] | None:
        """Every value a name bound only as a parameter of `fun` declarations can hold, or None when
        something else can bind it. Code cannot pass such a function as a value, so its calls are all
        visible. A missing argument is null."""
        functions = [function for function, params in self.functions.items() if name in params]
        if (
            not functions
            or name in self.declarations
            or any(fed == name for fed, _ in self.fed_names)
            or any(base == name for base, _, _ in self.member_assignments)
        ):
            return None
        feeds = [expr for assigned, expr in self.assignments if assigned == name]
        for function in functions:
            index = self.functions[function].index(name)
            feeds += [call.args[index] for call in self.calls if call.name == function and index < len(call.args)]
        return feeds

    def _scalar_input(self, key: str, seen: frozenset[str]) -> bool:
        marker = f"inputs.{key}"
        if marker in seen:
            return True
        if key not in self.definitions:
            # Only entering the secret again changes its value.
            return key in self.secret_keys
        for item in self.definitions[key]:
            value = item["value"]
            if isinstance(value, dict | list):
                return False
            if not isinstance(value, str) or item.get("templating") == "liquid" or item.get("templating") is False:
                continue
            try:
                expr = parse_string_template(value)
            except BaseHogQLError:
                return False
            if not self._scalar(expr, seen | {marker}):
                return False
        return True

    def _collect(self, node: ast.AST, function: str | None) -> None:
        """`function` is the enclosing `fun`, or empty inside a lambda and None at the top level."""
        if isinstance(node, ast.VariableDeclaration):
            self.declarations.add(node.name)
            if node.expr is None:
                self.unset_names.append(node.name)
            else:
                self.assignments.append((node.name, node.expr))
            if isinstance(node.expr, ast.Lambda):
                self.lambda_names[id(node.expr)] = node.name
                self._declare_callee(node)
        elif isinstance(node, ast.VariableAssignment):
            self.sending_reads.add(id(_assignment_target(node.left)))
            base, depth = _assignment_base(node.left)
            if depth == 0:
                self.assignments.append((base, node.right))
            else:
                keys = _assigned_keys(node.left)
                if _PROTOTYPE_KEYS.intersection(key for key in keys if key is not None):
                    raise _CannotAnalyze("unsupported_code")
                self.member_assignments += [(base, depth, expr) for expr in (node.right, *_computed_keys(node.left))]
                self.member_writes.append((base, keys, node.right))
        elif isinstance(node, ast.Function):
            if node.name in self.functions:
                raise _CannotAnalyze("unsupported_code")
            self.functions[node.name] = node.params
            self._declare_callee(node)
            function = node.name
        elif isinstance(node, ast.Lambda) and id(node) in self.lambda_names:
            self.named_lambda_args += [(name, self.lambda_names[id(node)]) for name in node.args]
            function = ""
        elif isinstance(node, ast.Lambda):
            self.fed_names += [(name, self.lambda_feeds.get(id(node))) for name in node.args]
            function = ""
        elif isinstance(node, ast.ReturnStatement) and node.expr is not None:
            # A top-level return hands its value to the worker: the event a transformation stores, or
            # the response a source webhook sends back to its caller.
            if function is None:
                self.exits.append(node.expr)
            elif function:
                self.returns.append((function, node.expr))
        elif isinstance(node, ast.ForInStatement):
            self.fed_names += [(name, [node.expr]) for name in (node.keyVar, node.valueVar) if name]
        elif isinstance(node, ast.TryCatchStatement):
            self.fed_names += [(name, None) for name, _, _ in node.catches if name]
        elif isinstance(node, ast.ThrowStatement):
            self.exits.append(node.expr)
        elif _is_unmodeled(node):
            raise _CannotAnalyze("unsupported_code")
        elif isinstance(node, _COMPARISONS):
            self.comparisons.append(node)
        elif isinstance(node, ast.ExprCall):
            self.exits += node.args
        elif isinstance(node, ast.Call):
            self.calls.append(node)
            if node.name == "fetch" and len(node.args) > 1:
                options = node.args[1]
                self.sending_reads.add(id(options))
                if isinstance(options, ast.Dict):
                    self.sending_reads |= {id(value) for key, value in options.items if _is_constant(key, "headers")}
            for arg in node.args if node.name in _ELEMENT_CALLBACK_CALLS else []:
                if isinstance(arg, ast.Lambda):
                    self.lambda_feeds[id(arg)] = [other for other in node.args if other is not arg]
        elif isinstance(node, ast.ArrayAccess) and isinstance(node.array, ast.Field) and node.array.chain == ["inputs"]:
            if id(node) not in self.sending_reads:
                key = _input_key(node)
                self.escaped.add("inputs" if key is None else f"inputs.{key}")
            self._collect(node.property, function)
            return
        elif isinstance(node, ast.Field):
            if id(node) not in self.sending_reads:
                head = str(node.chain[0])
                self.escaped.add(f"inputs.{node.chain[1]}" if head == "inputs" and len(node.chain) > 1 else head)
            self.field_heads.add(str(node.chain[0]))
            self.reads_all_inputs |= node.chain == ["inputs"]
        for child in _children(node):
            self._collect(child, function)

    def run(self) -> dict[str, SecretOrigins]:
        for name, _ in self.assignments:
            self.values[name] = frozenset()
        for params in self.functions.values():
            self.values.update(dict.fromkeys(params, frozenset()))
        for name, _ in self.fed_names:
            self.values[name] = _UNKNOWN
        self.values.update(dict.fromkeys(self.unset_names, _UNKNOWN))
        for _ in range(_MAX_ITERATIONS):
            if not self._step():
                break
        else:
            raise _CannotAnalyze("iterations")

        origins: dict[str, frozenset[str]] = dict.fromkeys(self.secret_keys, frozenset())
        shared = self._union_taint(self.shared_assignments)
        # Only a secret itself leaves this way. A digest of it or a response to it is logged, thrown and
        # stored by templates as a matter of course, and does not reveal it.
        unbound = set(_held(self._union_taint(self.exits) | (shared if self.exits else frozenset())))
        for call in self.calls:
            if call.name != "fetch":
                continue
            carried = self._fetch_carries(call, self._union_taint(call.args) | shared)
            if not carried:
                continue
            urls = self._value(call.args[0]) if call.args else _UNKNOWN
            found = {url_origin(text, complete) for text, complete in urls}
            hosts = self._options_hosts(call.args[1], frozenset()) if len(call.args) > 1 else frozenset()
            if hosts is None:
                found.add(None)
            else:
                # The URL's host still receives the request, so it keeps its origin next to the routed one.
                schemes = {origin.partition("://")[0] for origin in found if origin}
                found |= {url_origin(f"{scheme}://{host}", complete=True) for scheme in schemes for host in hosts}
            for key in carried:
                if None in found:
                    unbound.add(key)
                else:
                    origins[key] |= {origin for origin in found if origin}
        return {key: UNBOUND if key in unbound else value for key, value in origins.items()}

    def _options_hosts(self, node: ast.Expr, seen: frozenset[str]) -> frozenset[str] | None:
        """The hosts that the `Host` or `:authority` headers of fetch options name, or None when code or
        config can set a header the analysis does not see."""
        self._spend_evaluation()
        if isinstance(node, ast.Constant) and node.value is None:
            return frozenset()
        if isinstance(node, ast.Dict):
            entries: list[tuple[str | None, ast.Expr]] = [
                (key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None, value)
                for key, value in node.items
            ]
            return self._union_hosts(self._option_hosts(key, value, seen) for key, value in entries)
        resolved = self._container_sources(node, seen)
        if resolved is None:
            return None
        seen = resolved.seen
        return self._union_hosts(
            [self._options_hosts(source, seen) for source in resolved.sources]
            + [self._option_hosts(keys[0], value, seen) for keys, value in resolved.writes if len(keys) == 1]
            + [
                _header_entry_hosts(keys[1], value)
                for keys, value in resolved.writes
                if len(keys) == 2 and keys[0] in ("headers", None)
            ]
        )

    def _option_hosts(self, key: str | None, value: ast.Expr, seen: frozenset[str]) -> frozenset[str] | None:
        if key == "headers":
            return self._header_hosts(value, seen)
        if key == "secret_headers_input":
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return self._configured_header_hosts(value.value)
            return None
        return None if key is None else frozenset()

    def _header_hosts(self, node: ast.Expr, seen: frozenset[str]) -> frozenset[str] | None:
        self._spend_evaluation()
        if isinstance(node, ast.Constant) and node.value is None:
            return frozenset()
        if isinstance(node, ast.Dict):
            return self._union_hosts(
                _header_entry_hosts(key.value if isinstance(key, ast.Constant) else None, value)
                for key, value in node.items
            )
        input_key = _input_key(node)
        if input_key is not None and not (isinstance(node, ast.Field) and len(node.chain) > 2):
            if self._written_from_elsewhere(f"inputs.{input_key}"):
                return None
            return self._configured_header_hosts(input_key)
        resolved = self._container_sources(node, seen)
        if resolved is None:
            return None
        return self._union_hosts(
            [self._header_hosts(source, resolved.seen) for source in resolved.sources]
            + [_header_entry_hosts(keys[0], value) for keys, value in resolved.writes if len(keys) == 1]
        )

    def _configured_header_hosts(self, key: str) -> frozenset[str] | None:
        hosts: set[str] = set()
        for item in self.definitions.get(key, []):
            value = item["value"]
            if value is None:
                continue
            if not isinstance(value, dict):
                return None
            for name, header in value.items():
                # The worker expands this key into more entries, which can include a Host header.
                if not isinstance(name, str) or name == "$$_extend_object" or name in _PROTOTYPE_KEYS:
                    return None
                if name.lower() not in _HOST_HEADERS:
                    continue
                # Any templating can make the host whatever an event says.
                if not isinstance(header, str) or "{" in header:
                    return None
                hosts.add(header)
        return frozenset(hosts)

    def _container_sources(self, node: ast.Expr, seen: frozenset[str]) -> _ContainerSources | None:
        """None when the dict can come from somewhere the analysis does not see."""
        if isinstance(node, ast.Field) and len(node.chain) == 1 and str(node.chain[0]) in self.fresh_containers:
            name = str(node.chain[0])
            if self._written_from_elsewhere(name):
                return None
            if name in seen:
                return _ContainerSources(sources=[], writes=[], seen=seen)
            sources = [expr for assigned, expr in self.assignments if assigned == name]
            writes = [(keys, value) for base, keys, value in self.member_writes if base == name]
            return _ContainerSources(sources=sources, writes=writes, seen=seen | {name})
        if isinstance(node, ast.Call) and node.name in self.functions:
            marker = f"{node.name}()"
            if marker in seen:
                return _ContainerSources(sources=[], writes=[], seen=seen)
            returned = [expr for function, expr in self.returns if function == node.name]
            return _ContainerSources(sources=returned, writes=[], seen=seen | {marker})
        if isinstance(node, ast.Call) and node.name in ("coalesce", "ifNull"):
            return _ContainerSources(sources=list(node.args), writes=[], seen=seen)
        if isinstance(node, ast.Call) and node.name == "if" and len(node.args) == 3:
            return _ContainerSources(sources=list(node.args[1:]), writes=[], seen=seen)
        return None

    def _written_from_elsewhere(self, holder: str) -> bool:
        """Whether code can set a host header on the dict `holder` names through another name. That needs
        a write with a computed or host key, and the dict reaching code other than the fetch that sends it."""
        escaped = holder in self.escaped or (holder.startswith("inputs.") and "inputs" in self.escaped)
        return escaped and any(base != holder for base in self.host_write_bases)

    @staticmethod
    def _union_hosts(found: Iterable[frozenset[str] | None]) -> frozenset[str] | None:
        hosts: set[str] = set()
        for item in found:
            if item is None:
                return None
            hosts |= item
        return frozenset(hosts)

    def _fetch_carries(self, call: ast.Call, taint: _Taint) -> frozenset[str]:
        """The secrets a fetch sends: those its arguments hold or were derived from, and every secret
        when its options can name one."""
        if len(call.args) > 1 and not _names_no_input(call.args[1]):
            return self.secret_keys
        return _reached(taint)

    def _step(self) -> bool:
        changed = False

        def add(name: str, values: _Values, taint: _Taint, returns: bool = False) -> None:
            nonlocal changed
            value_map, taint_map = (self.return_values, self.return_taints) if returns else (self.values, self.taints)
            old_values, old_taint = value_map.get(name, frozenset()), taint_map.get(name, frozenset())
            new_values, new_taint = _normalize(old_values | values), old_taint | taint
            if (new_values, new_taint) != (old_values, old_taint):
                value_map[name], taint_map[name], changed = new_values, new_taint, True

        for name, expr in self.assignments:
            add(name, self._value(expr), self._taint(expr))
        for name, _, expr in self.member_assignments:
            add(name, _UNKNOWN, self._taint(expr))
        for name, feed in self.fed_names:
            add(name, _UNKNOWN, self.secret_keys if feed is None else self._union_taint(feed))
        for name in self.unset_names:
            add(name, _UNKNOWN, frozenset())
        for call in self.calls:
            for index, param in enumerate(self.functions.get(call.name, [])):
                arg = call.args[index] if index < len(call.args) else None
                add(param, self._value(arg) if arg else _UNKNOWN, self._taint(arg) if arg else frozenset())
        for function, expr in self.returns:
            add(function, self._value(expr), self._taint(expr), returns=True)
        return changed

    def _union_taint(self, nodes: Iterable[ast.AST]) -> _Taint:
        return frozenset().union(*(self._taint(node) for node in nodes))

    def _spend_evaluation(self) -> None:
        self.evaluations_left -= 1
        if self.evaluations_left < 0:
            raise _CannotAnalyze("budget")

    def _value(self, node: ast.Expr) -> _Values:
        self._spend_evaluation()
        if isinstance(node, ast.Constant):
            return frozenset({(node.value, True)}) if isinstance(node.value, str) else _UNKNOWN
        input_key = _input_key(node)
        if input_key is not None:
            is_member = isinstance(node, ast.Field) and len(node.chain) > 2
            return _UNKNOWN if is_member else self.inputs.get(input_key, (_UNKNOWN,))[0]
        if isinstance(node, ast.Field) and len(node.chain) == 1:
            return self.values.get(str(node.chain[0]), _UNKNOWN)
        if isinstance(node, ast.Call):
            if node.name == "concat":
                return _concat([self._value(arg) for arg in node.args])
            if node.name in ("ifNull", "coalesce"):
                return _normalize(frozenset().union(*(self._value(arg) for arg in node.args)))
            if node.name == "if" and len(node.args) == 3:
                return _normalize(self._value(node.args[1]) | self._value(node.args[2]))
            if node.name in self.functions:
                return self.return_values.get(node.name, frozenset())
        return _UNKNOWN

    def _taint(self, node: ast.AST) -> _Taint:
        self._spend_evaluation()
        if isinstance(node, ast.Constant):
            return frozenset({node.value}) & self.secret_keys if isinstance(node.value, str) else frozenset()
        input_key = _input_key(node)
        if input_key is not None:
            return self.inputs.get(input_key, (_UNKNOWN, frozenset()))[1]
        if isinstance(node, ast.Field) and node.chain[0] == "inputs":
            return self.secret_keys
        if isinstance(node, ast.Field):
            return self.taints.get(str(node.chain[0]), frozenset())
        if isinstance(node, ast.Dict):
            # Keys are excluded because the worker only ever resolves a secret named by a value.
            return self._union_taint(
                [value for _, value in node.items] + [key for key, _ in node.items if not isinstance(key, ast.Constant)]
            )
        if isinstance(node, ast.Call) and node.name in self.functions:
            return self.return_taints.get(node.name, frozenset())
        if isinstance(node, ast.Call) and node.name in self.lambdas_only:
            return self.taints.get(node.name, frozenset())
        taint = self._union_taint(_children(node))
        if isinstance(node, ast.Call) and node.name == "fetch":
            # A response can echo what its request sent, so passing it on moves those secrets too.
            return _derived(self._fetch_carries(node, taint))
        if isinstance(node, ast.Call) and node.name in _DIGEST_CALLS:
            return _derived(taint)
        if (isinstance(node, ast.Call) and node.name in _PIECE_CALLS) or isinstance(node, _PIECE_EXPRS):
            return _pieces(taint)
        if isinstance(node, ast.Call):
            return taint | self.taints.get(node.name, frozenset())
        if isinstance(node, ast.Array | ast.Tuple):
            return taint
        # Arithmetic, indexing and every other operator can keep only part of a value, such as one digit or
        # one character, and a digest of that part can be reversed by trying each value it can have.
        return _pieces(taint)


def _is_unmodeled(node: ast.AST) -> bool:
    # In `f(a)(b)` the VM runs `f(a)` and then calls its result, so a second argument list is a call that
    # this analysis does not model.
    if isinstance(node, ast.Call):
        return node.params is not None
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value in _PROTOTYPE_KEYS for key, _ in node.items
    )


def _names_no_input(options: ast.Expr) -> bool:
    # The worker resolves these options to any stored input by name, and the name can come from event data.
    return isinstance(options, ast.Dict) and all(
        isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value not in _BY_NAME_OPTIONS
        for key, _ in options.items
    )


def _calls_back_inline(call: ast.Call) -> bool:
    """The library code quotes neither argument, so only what the inline lambda does can carry a value out."""
    return call.name in _ELEMENT_CALLBACK_CALLS and bool(call.args) and isinstance(call.args[0], ast.Lambda)


def _input_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Field) and node.chain[0] == "inputs" and len(node.chain) > 1:
        return str(node.chain[1])
    if (
        isinstance(node, ast.ArrayAccess)
        and isinstance(node.array, ast.Field)
        and node.array.chain == ["inputs"]
        and isinstance(node.property, ast.Constant)
        and isinstance(node.property.value, str)
    ):
        return node.property.value
    return None
