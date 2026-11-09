"""Which origins a hog function's code can send each of its secret inputs to.

The analysis is flow-insensitive and conservative. Every assignment to a name counts wherever it
appears, and a secret whose destination cannot be pinned to known origins is `UNBOUND`.
"""

import re
import dataclasses
from collections.abc import Iterable, Iterator, Mapping
from enum import Enum
from secrets import token_hex
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
_MAX_ITERATIONS = 64
# Expression evaluations one analysis may make. The budget sits far above what real templates need, so
# only a source written to be slow runs out, and the analysis then treats it as one it cannot pin down.
_MAX_EVALUATIONS = 25_000
_SCHEME = re.compile(r"(https?)://", re.IGNORECASE)
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_UNSAFE_AUTHORITY = re.compile(r"[@\\%\s\x00-\x1f\x7f]")
_NUMERIC_LABEL = re.compile(r"^(\d+|0x[0-9a-f]*)$")
_BY_NAME_OPTIONS = frozenset({"secret_headers_input", "standard_webhooks", "aws_sigv4"})
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


_Taint = frozenset[str | _Derived]


def _derived(taint: _Taint) -> _Taint:
    return frozenset(_Derived(key=item) if isinstance(item, str) else item for item in taint)


def _held(taint: _Taint) -> frozenset[str]:
    return frozenset(item for item in taint if isinstance(item, str))


def _reached(taint: _Taint) -> frozenset[str]:
    return frozenset(item.key if isinstance(item, _Derived) else item for item in taint)


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


def mapping_inputs(mappings: Any) -> list[dict[str, Any]]:
    return [mapping.get("inputs") or {} for mapping in mappings or [] if isinstance(mapping, dict)]


def stored_origins(origins: SecretOrigins) -> str | list[str]:
    return UNBOUND.value if origins is UNBOUND else sorted(origins)


def parse_stored_origins(stored: Any) -> SecretOrigins | None:
    if stored == UNBOUND.value:
        return UNBOUND
    if isinstance(stored, list) and all(isinstance(origin, str) for origin in stored):
        return frozenset(stored)
    return None


@frozen
class SecretDestinations:
    """Where a secret goes, told without the value of any secret."""

    hosts: frozenset[str]
    # Secret inputs whose values give the host of an address the secret goes to.
    built_from: frozenset[str]


def public_secret_destinations(
    hog: str, inputs: dict[str, Any], mapping_input_sets: list[dict[str, Any]], secret_keys: set[str]
) -> dict[str, SecretDestinations | Unbound]:
    """Where each secret goes, for someone who may not read the secrets. Each secret input holds a
    placeholder instead of its value, so no part of the answer depends on a secret's value."""
    # A random placeholder cannot be written into the code, so a host the code names is never taken for
    # one built from a secret.
    placeholders = {key: f"secret{token_hex(8)}" for key in secret_keys}
    input_sets = [
        {
            key: {**item, "value": placeholders[key]} if key in placeholders and isinstance(item, dict) else item
            for key, item in (input_set or {}).items()
        }
        for input_set in [inputs, *mapping_input_sets]
    ]
    try:
        return _Analysis(hog, input_sets, secret_keys).destinations(placeholders)
    except (_CannotAnalyze, BaseHogQLError, RecursionError):
        return dict.fromkeys(secret_keys, UNBOUND)


_MAX_LISTED_ADDRESSES = 3


def _addresses(destinations: SecretDestinations, labels: Mapping[str, str]) -> list[str]:
    hosts = sorted(origin.removeprefix("https://") for origin in destinations.hosts)
    built = sorted(f"an address built from {labels.get(key, key)}" for key in destinations.built_from)
    return hosts + built


def _listed(addresses: list[str]) -> str:
    if len(addresses) > _MAX_LISTED_ADDRESSES:
        addresses = [*addresses[:_MAX_LISTED_ADDRESSES], f"{len(addresses) - _MAX_LISTED_ADDRESSES} more"]
    return f"{', '.join(addresses[:-1])} and {addresses[-1]}" if len(addresses) > 1 else addresses[0]


def secret_reentry_message(
    key: str,
    now: SecretDestinations | Unbound,
    before: SecretDestinations | Unbound,
    labels: Mapping[str, str],
) -> str:
    """Why a save that moves the stored secret `key` needs it entered again. `labels` names each input
    the way the editor shows it."""
    label = labels.get(key, key)
    if isinstance(now, Unbound):
        now_text = f"PostHog can't tell where this change sends {label}."
    else:
        # Only what it was not sent to before is named, so the cap on the list never hides a new address.
        new = (
            SecretDestinations(hosts=now.hosts - before.hosts, built_from=now.built_from - before.built_from)
            if isinstance(before, SecretDestinations)
            else now
        )
        addresses = _addresses(new, labels) or _addresses(now, labels)
        now_text = (
            f"This change sends {label} to {_listed(addresses)}."
            if addresses
            else f"This change stops sending {label} anywhere."
        )
    if isinstance(before, Unbound):
        before_text = "Until now PostHog couldn't tell where it was sent."
    elif before_addresses := _addresses(before, labels):
        before_text = f"Until now it was only sent to {_listed(before_addresses)}."
    else:
        before_text = "Until now it wasn't sent anywhere."
    return f"{now_text} {before_text} Enter it again to confirm."


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
    return port.isdigit() and not port.startswith("0") and int(port) <= 65535


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


def _normalize(values: _Values) -> _Values:
    return _UNKNOWN if ("", False) in values or len(values) > _MAX_VALUES else values


def _concat(parts: list[_Values]) -> _Values:
    joined: _Values = frozenset({("", True)})
    for part in parts:
        joined = _normalize(
            frozenset(
                (text + more, more_complete) if complete else (text, False)
                for text, complete in joined
                for more, more_complete in (part if complete else [("", False)])
            )
        )
    return joined


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
        self.named_lambda_args: list[tuple[str, str]] = []
        self.lambdas_only: set[str] = set()
        # Expressions whose value can leave the function other than through `fetch`.
        self.exits: list[ast.Expr] = []
        self.shared_taint: _Taint = frozenset()

        self.definitions: dict[str, list[dict]] = {}
        for input_set in input_sets:
            for key, item in (input_set or {}).items():
                if isinstance(item, dict) and "value" in item:
                    self.definitions.setdefault(key, []).append(item)
        self.inputs: dict[str, tuple[_Values, _Taint]] = {}
        for key in self.definitions:
            self._input(key, set())

        self._collect(parse_program(hog), None)
        self.fed_names += [(arg, self._call_arguments(name)) for arg, name in self.named_lambda_args]
        bound_elsewhere = {name for name, _ in self.fed_names}
        bound_elsewhere |= {param for params in self.functions.values() for param in params}
        variables = {name for name, _ in self.assignments} | self.declarations | bound_elsewhere
        fresh = self._fresh_container_names() - bound_elsewhere
        self.shared_assignments = [
            expr for base, depth, expr in self.member_assignments if depth > 1 or base not in fresh
        ]
        if self._rebinds_an_interpreted_name(variables) or self._hands_on_a_callee() or self._can_replace_inputs():
            raise _CannotAnalyze("unsupported_code")

        local = self.declarations | bound_elsewhere | set(self.functions)
        self.lambdas_only = self._lambda_only_names() - bound_elsewhere - set(self.functions)
        self.exits += [expr for base, _, expr in self.member_assignments if base not in local]
        self.exits += [expr for name, expr in self.assignments if name not in local]
        self.assigned_only = self.declarations - bound_elsewhere - {base for base, _, _ in self.member_assignments}
        self.exits += self._compared_exits(self.comparisons)
        quiet = {"fetch", *_SAFE_CALLS, *self.functions, *self.lambdas_only}
        self.exits += [
            arg for call in self.calls if call.name not in quiet and not _calls_back_inline(call) for arg in call.args
        ]

    def _rebinds_an_interpreted_name(self, variables: set[str]) -> bool:
        functions = set(self.functions)
        return bool((variables | functions) & _INTERPRETED_NAMES or variables & functions)

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
        for key in {key for node in nodes if (key := _input_key(node)) is not None}:
            self._input(key, resolving)
        self.exits += [
            arg for node in nodes if isinstance(node, ast.Call) and node.name not in _SAFE_CALLS for arg in node.args
        ]
        self.exits += self._compared_exits(node for node in nodes if isinstance(node, _COMPARISONS))
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
        if name not in self.assigned_only:
            return False
        return all(self._scalar(expr, seen | {name}) for assigned, expr in self.assignments if assigned == name)

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
            if not isinstance(value, str) or item.get("templating") == "liquid":
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
            if node.expr is not None:
                self.assignments.append((node.name, node.expr))
            if isinstance(node.expr, ast.Lambda):
                self.lambda_names[id(node.expr)] = node.name
        elif isinstance(node, ast.VariableAssignment):
            base, depth = _assignment_base(node.left)
            if depth == 0:
                self.assignments.append((base, node.right))
            else:
                self.member_assignments.append((base, depth, node.right))
        elif isinstance(node, ast.Function):
            if node.name in self.functions:
                raise _CannotAnalyze("unsupported_code")
            self.functions[node.name] = node.params
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
        elif isinstance(node, _COMPARISONS):
            self.comparisons.append(node)
        elif isinstance(node, ast.ExprCall):
            self.exits += node.args
        elif isinstance(node, ast.Call):
            self.calls.append(node)
            for arg in node.args if node.name in _ELEMENT_CALLBACK_CALLS else []:
                if isinstance(arg, ast.Lambda):
                    self.lambda_feeds[id(arg)] = [other for other in node.args if other is not arg]
        elif isinstance(node, ast.ArrayAccess) and isinstance(node.array, ast.Field) and node.array.chain == ["inputs"]:
            self._collect(node.property, function)
            return
        elif isinstance(node, ast.Field):
            self.field_heads.add(str(node.chain[0]))
            self.reads_all_inputs |= node.chain == ["inputs"]
        for child in _children(node):
            self._collect(child, function)

    def run(self) -> dict[str, SecretOrigins]:
        self._settle()
        origins: dict[str, frozenset[str]] = dict.fromkeys(self.secret_keys, frozenset())
        unbound = self._leaving_secrets()
        for carried, urls in self._fetches():
            found = {url_origin(text, complete) for text, complete in urls}
            for key in carried:
                if None in found:
                    unbound.add(key)
                else:
                    origins[key] |= {origin for origin in found if origin}
        return {key: UNBOUND if key in unbound else value for key, value in origins.items()}

    def destinations(self, placeholders: Mapping[str, str]) -> dict[str, SecretDestinations | Unbound]:
        """Where each secret goes while every secret input holds its placeholder. An address whose host holds
        a placeholder, or that starts with one, is built from that secret."""
        self._settle()
        hosts: dict[str, set[str]] = {key: set() for key in self.secret_keys}
        built_from: dict[str, set[str]] = {key: set() for key in self.secret_keys}
        unbound = self._leaving_secrets()
        for carried, urls in self._fetches():
            for text, complete in urls:
                origin = url_origin(text, complete)
                builders = {
                    key
                    for key, placeholder in placeholders.items()
                    if (placeholder in origin if origin else text.startswith(placeholder))
                }
                for key in carried:
                    if builders:
                        built_from[key] |= builders
                    elif origin is None:
                        unbound.add(key)
                    else:
                        hosts[key].add(origin)
        return {
            key: UNBOUND
            if key in unbound
            else SecretDestinations(hosts=frozenset(hosts[key]), built_from=frozenset(built_from[key]))
            for key in self.secret_keys
        }

    def _settle(self) -> None:
        for name, _ in self.assignments:
            self.values[name] = frozenset()
        for params in self.functions.values():
            self.values.update(dict.fromkeys(params, frozenset()))
        for name, _ in self.fed_names:
            self.values[name] = _UNKNOWN
        for _ in range(_MAX_ITERATIONS):
            if not self._step():
                break
        else:
            raise _CannotAnalyze("iterations")
        self.shared_taint = self._union_taint(self.shared_assignments)

    def _leaving_secrets(self) -> set[str]:
        # Only a secret itself leaves this way. A digest of it or a response to it is logged, thrown and
        # stored by templates as a matter of course, and does not reveal it.
        return set(_held(self._union_taint(self.exits) | (self.shared_taint if self.exits else frozenset())))

    def _fetches(self) -> Iterator[tuple[frozenset[str], _Values]]:
        """The secrets each fetch sends, with the addresses it can send them to."""
        for call in self.calls:
            if call.name != "fetch":
                continue
            carried = self._fetch_carries(call, self._union_taint(call.args) | self.shared_taint)
            if carried:
                yield carried, self._value(call.args[0]) if call.args else _UNKNOWN

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
        if isinstance(node, ast.Call):
            taint |= self.taints.get(node.name, frozenset())
        return taint


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
