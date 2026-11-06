"""Which origins a hog function's code can send each of its secret inputs to.

The analysis is flow-insensitive and conservative. Every assignment to a name counts wherever it
appears, and a secret whose destination cannot be pinned to known origins is `UNBOUND`.
"""

import re
import dataclasses
from collections.abc import Iterable, Iterator
from enum import Enum
from typing import Any

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_program, parse_string_template


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
# Calls other than `fetch` that carry their arguments out of the function: into logs, events or other
# PostHog records. The worker registers the async ones in nodejs/src/cdp/async-functions/.
_EMITTING_CALLS = frozenset(
    {
        "print",
        "postHogCapture",
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
# Standard library calls that call their lambda argument with elements of their other arguments. Other
# callees, such as `arrayReduce` with its accumulator or code the template defines, can call a lambda with
# any value.
_ELEMENT_CALLBACK_CALLS = frozenset({"arrayMap", "arrayFilter", "arrayExists", "arrayCount"})
# Names the analysis gives a meaning to. Code that declares one of them replaces that meaning at runtime.
_INTERPRETED_NAMES = (
    frozenset({"inputs", "fetch", "concat", "coalesce", "ifNull", "if"}) | _EMITTING_CALLS | _ELEMENT_CALLBACK_CALLS
)
_FRESH_CONTAINERS = (ast.Dict, ast.Array, ast.Tuple)


class _CannotAnalyze(Exception):
    pass


def secret_origins(
    hog: str, inputs: dict[str, Any], mapping_input_sets: list[dict[str, Any]], secret_keys: set[str]
) -> dict[str, SecretOrigins]:
    try:
        return _Analysis(hog, [inputs, *mapping_input_sets], secret_keys).run()
    except (_CannotAnalyze, BaseHogQLError, RecursionError):
        return dict.fromkeys(secret_keys, UNBOUND)


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
        raise _CannotAnalyze
    return left.chain[0], depth + len(left.chain) - 1


class _Analysis:
    def __init__(self, hog: str, input_sets: list[dict[str, Any]], secret_keys: set[str]) -> None:
        self.secret_keys = frozenset(secret_keys)
        self.evaluations_left = _MAX_EVALUATIONS
        self.values: dict[str, _Values] = {}
        self.taints: dict[str, frozenset[str]] = {}
        self.return_values: dict[str, _Values] = {}
        self.return_taints: dict[str, frozenset[str]] = {}
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
        self.thrown: list[ast.Expr] = []
        self.field_heads: set[str] = set()
        self.lambda_feeds: dict[int, list[ast.Expr]] = {}
        # Lambdas a declaration binds to a name, and the parameters of each with that name.
        self.lambda_names: dict[int, str] = {}
        self.named_lambda_args: list[tuple[str, str]] = []

        self.definitions: dict[str, list[dict]] = {}
        for input_set in input_sets:
            for key, item in (input_set or {}).items():
                if isinstance(item, dict) and "value" in item:
                    self.definitions.setdefault(key, []).append(item)
        self.inputs: dict[str, tuple[_Values, frozenset[str]]] = {}
        for key in self.definitions:
            self._input(key, set())

        self._collect(parse_program(hog), None)
        self.fed_names += [(arg, self._call_arguments(name)) for arg, name in self.named_lambda_args]
        bound_elsewhere = {name for name, _ in self.fed_names}
        bound_elsewhere |= {param for params in self.functions.values() for param in params}
        variables = {name for name, _ in self.assignments} | bound_elsewhere
        fresh = self._fresh_container_names() - bound_elsewhere
        self.shared_assignments = [
            expr for base, depth, expr in self.member_assignments if depth > 1 or base not in fresh
        ]
        if (
            (variables | set(self.functions)) & _INTERPRETED_NAMES
            or variables & set(self.functions)
            or self.field_heads & {"fetch", *_EMITTING_CALLS, *self.functions}
            # The analysis reads input values as configured, so code must not be able to replace them.
            or any(base == "inputs" for base, _, _ in self.member_assignments)
            or (self.reads_all_inputs and self.shared_assignments)
        ):
            raise _CannotAnalyze

    def _call_arguments(self, lambda_name: str) -> list[ast.Expr] | None:
        """Every argument of every call to a name that only declarations of lambdas bind, or None when the
        lambda can be reached another way. A name used as a value can hand the lambda to code that calls
        it with any argument."""
        params = {param for params in self.functions.values() for param in params}
        bound_otherwise = {name for name, _ in self.fed_names} | {arg for arg, _ in self.named_lambda_args} | params
        lambdas_only = all(isinstance(expr, ast.Lambda) for name, expr in self.assignments if name == lambda_name)
        if not lambdas_only or lambda_name in self.field_heads | bound_otherwise | set(self.functions):
            return None
        return [arg for call in self.calls if call.name == lambda_name for arg in call.args]

    def _fresh_container_names(self) -> set[str]:
        """Names only ever assigned a new dict, array or tuple. No other name reaches that object, so
        taint from a member assignment on it is carried by reads of the name."""
        stale = {name for name, expr in self.assignments if not isinstance(expr, _FRESH_CONTAINERS)}
        return {name for name, _ in self.assignments} - stale

    def _input(self, key: str, resolving: set[str]) -> tuple[_Values, frozenset[str]]:
        if key in self.inputs:
            return self.inputs[key]
        if key in resolving:
            raise _CannotAnalyze
        resolving.add(key)
        values: _Values = frozenset() if key in self.definitions else _UNKNOWN
        taint = frozenset({key}) & self.secret_keys
        for item in self.definitions.get(key, []):
            item_values, item_taint = self._template(item["value"], item.get("templating"), resolving)
            values, taint = _normalize(values | item_values), taint | item_taint
        self.inputs[key] = (values, taint)
        return self.inputs[key]

    def _template(self, value: Any, templating: Any, resolving: set[str]) -> tuple[_Values, frozenset[str]]:
        if isinstance(value, dict | list):
            taint: frozenset[str] = frozenset()
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
        for key in self._input_references(expr):
            self._input(key, resolving)
        return self._value(expr), self._taint(expr)

    def _input_references(self, node: ast.AST) -> Iterator[str]:
        input_key = _input_key(node)
        if input_key is not None:
            yield input_key
        for child in _children(node):
            yield from self._input_references(child)

    def _collect(self, node: ast.AST, function: str | None) -> None:
        if isinstance(node, ast.VariableDeclaration) and node.expr is not None:
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
                raise _CannotAnalyze
            self.functions[node.name] = node.params
            function = node.name
        elif isinstance(node, ast.Lambda) and id(node) in self.lambda_names:
            self.named_lambda_args += [(name, self.lambda_names[id(node)]) for name in node.args]
            function = None
        elif isinstance(node, ast.Lambda):
            self.fed_names += [(name, self.lambda_feeds.get(id(node))) for name in node.args]
            function = None
        elif isinstance(node, ast.ReturnStatement) and function and node.expr is not None:
            self.returns.append((function, node.expr))
        elif isinstance(node, ast.ForInStatement):
            self.fed_names += [(name, [node.expr]) for name in (node.keyVar, node.valueVar) if name]
        elif isinstance(node, ast.TryCatchStatement):
            self.fed_names += [(name, None) for name, _, _ in node.catches if name]
        elif isinstance(node, ast.ThrowStatement):
            self.thrown.append(node.expr)
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
            raise _CannotAnalyze

        origins: dict[str, frozenset[str]] = dict.fromkeys(self.secret_keys, frozenset())
        shared = self._union_taint(self.shared_assignments)
        emits = bool(self.thrown) or any(call.name in _EMITTING_CALLS for call in self.calls)
        unbound: set[str] = set(self._union_taint(self.thrown)) | (shared if emits else set())
        for call in self.calls:
            if call.name in _EMITTING_CALLS:
                unbound |= self._union_taint(call.args)
            if call.name != "fetch":
                continue
            carried = self._union_taint(call.args) | shared
            if len(call.args) > 1 and not _names_no_input(call.args[1]):
                carried = self.secret_keys
            if not carried:
                continue
            found = {url_origin(text, complete) for text, complete in self._value(call.args[0])}
            for key in carried:
                if None in found:
                    unbound.add(key)
                else:
                    origins[key] |= {origin for origin in found if origin}
        return {key: UNBOUND if key in unbound else value for key, value in origins.items()}

    def _step(self) -> bool:
        changed = False

        def add(name: str, values: _Values, taint: frozenset[str], returns: bool = False) -> None:
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

    def _union_taint(self, nodes: Iterable[ast.AST]) -> frozenset[str]:
        return frozenset().union(*(self._taint(node) for node in nodes))

    def _spend_evaluation(self) -> None:
        self.evaluations_left -= 1
        if self.evaluations_left < 0:
            raise _CannotAnalyze

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

    def _taint(self, node: ast.AST) -> frozenset[str]:
        self._spend_evaluation()
        if isinstance(node, ast.Call) and node.name == "fetch":
            # The response holds what the bound origin sends back, not the secrets sent to it.
            return frozenset()
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
        taint = self._union_taint(_children(node))
        if isinstance(node, ast.Call):
            taint |= self.taints.get(node.name, frozenset()) | self.return_taints.get(node.name, frozenset())
        return taint


def _names_no_input(options: ast.Expr) -> bool:
    # The worker resolves these options to any stored input by name, and the name can come from event data.
    return isinstance(options, ast.Dict) and all(
        isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value not in _BY_NAME_OPTIONS
        for key, _ in options.items
    )


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
