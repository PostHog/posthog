import re
from collections.abc import Iterable, Mapping
from typing import Final, cast

from .errors import RecipeCompileError
from .expressions import (
    ArrayExpr,
    CoalesceExpr,
    Expr,
    InterpExpr,
    JoinExpr,
    LiteralExpr,
    ObjectExpr,
    OmitExpr,
    PathExpr,
    RejectExpr,
    SelectExpr,
    SelfExpr,
    StringifyExpr,
    TryParseStructuredContentExpr,
)
from .predicates import (
    EqualsPredicate,
    EveryPredicate,
    ExistsPredicate,
    InPredicate,
    IsPredicate,
    Pattern,
    Predicate,
    ShapePredicate,
    TypeName,
)
from .rules import (
    DelegateEachRule,
    DelegateRule,
    EmitRule,
    EmitSpec,
    ExpandFollowup,
    Followup,
    Recipe,
    RoleTag,
    Rule,
    StaticFollowup,
)
from .run_limits import check_time_limit
from .values import MISSING, Missing, Value, is_truthy, key_text, to_json_text

PREDICATE_VERBS: Final = ("equals", "exists", "is", "in", "shape", "every")
ROLE_TAGS: Final = frozenset({"user", "assistant", "system", "tool", "thinking", "tool_result"})
TYPE_NAMES: Final = frozenset({"string", "array", "object", "null", "number", "boolean", "any"})
OPERATORS: Final = (
    "select",
    "reject",
    "coalesce",
    "join",
    "omit",
    "try_parse_structured_content",
    "stringify",
    "literal",
)

# Team recipes compile on the trace read path. The loader rejects YAML aliases, so a compile is linear in the source,
# and the source length cap together with this node budget bounds the work of one compile.
COMPILE_NODE_BUDGET: Final = 100_000

# The ASCII flag keeps `\w` to the identifier characters JavaScript's `\w` matches.
_BARE_FIELD: Final = re.compile(r"[A-Za-z_]\w*", re.ASCII)
_PATH: Final = re.compile(r"\$\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII)
_INTERP: Final = re.compile(r"\$\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)", re.ASCII)
_ROOTLESS_FIELD: Final = re.compile(r"\$[A-Za-z_]")

type _Items = list[tuple[str, object]]


def compile_recipe(raw: object, fallback_id: str | None = None) -> Recipe:
    # Custom recipes are keyed by their database id, so their source never needs to declare one.
    try:
        return _RecipeCompiler().recipe(raw, fallback_id)
    except RecursionError as error:
        raise RecipeCompileError("Recipe nests too deeply to compile") from error


def nearest_operator(key: str, operators: Iterable[str]) -> str | None:
    return next((operator for operator in operators if _within_one_edit(key, operator)), None)


def _within_one_edit(a: str, b: str) -> bool:
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1 :] == b[i + 1 :]
    if len(a) < len(b):
        return a[i:] == b[i + 1 :]
    return a[i + 1 :] == b[i:]


def _as_mapping(raw: object) -> _Items | None:
    if not isinstance(raw, Mapping):
        return None
    return [(key_text(key), value) for key, value in raw.items()]


class _RecipeCompiler:
    def __init__(self) -> None:
        self._nodes = 0

    def recipe(self, raw: object, fallback_id: str | None) -> Recipe:
        items = _as_mapping(raw)
        if items is None:
            raise RecipeCompileError("Recipe YAML must be a mapping at top level")
        fields = dict(items)
        raw_id = fields.get("id")
        recipe_id = raw_id if isinstance(raw_id, str) else fallback_id
        if not recipe_id:
            raise RecipeCompileError("Recipe is missing an 'id' key")
        rules_raw = fields.get("rules")
        if not isinstance(rules_raw, list):
            raise RecipeCompileError(f"Recipe '{recipe_id}' is missing a 'rules:' sequence")
        rules: list[Rule] = []
        for index, rule_raw in enumerate(rules_raw):
            try:
                rules.append(self._rule(rule_raw))
            except RecipeCompileError as error:
                raise RecipeCompileError(f"Recipe '{recipe_id}' rule[{index}]: {error}") from error
        return Recipe(id=recipe_id, rules=tuple(rules))

    def _count(self) -> None:
        self._nodes += 1
        if self._nodes > COMPILE_NODE_BUDGET:
            raise RecipeCompileError(f"the recipe compiles to more than {COMPILE_NODE_BUDGET} nodes; simplify it")
        # A caller that compiles inside a deadline, such as a trace read, can stop a compile that runs too long.
        check_time_limit()

    def _rule(self, raw: object) -> Rule:
        self._count()
        items = _as_mapping(raw)
        if items is None:
            raise RecipeCompileError("rule must be a mapping")
        fields = dict(items)
        on_items = _as_mapping(fields.get("on"))
        if on_items is None:
            raise RecipeCompileError("rule.on must be a mapping")
        on = self._pattern(on_items)
        followups = self._followups(fields.get("followups", MISSING))
        if "delegate" in fields:
            return DelegateRule(on=on, followups=followups, source=self._value(fields["delegate"]))
        if "delegateEach" in fields:
            stamp = self._emit_spec(fields["stamp"]) if "stamp" in fields else None
            return DelegateEachRule(on=on, followups=followups, source=self._value(fields["delegateEach"]), stamp=stamp)
        if "emit" in fields:
            return EmitRule(on=on, followups=followups, emit=self._emit_spec(fields["emit"]))
        raise RecipeCompileError("Rule must set one of: emit, delegate, delegateEach")

    def _followups(self, raw: object) -> tuple[Followup, ...]:
        if isinstance(raw, Missing):
            return ()
        if not isinstance(raw, list):
            raise RecipeCompileError("rule.followups must be a sequence")
        return tuple(self._followup(item) for item in raw)

    def _followup(self, raw: object) -> Followup:
        self._count()
        items = _as_mapping(raw)
        if items is None:
            raise RecipeCompileError("followup entry must be a mapping")
        fields = dict(items)
        if "from" in fields and "each" in fields:
            if _as_mapping(fields["each"]) is None:
                raise RecipeCompileError("'each:' in followup must be a mapping")
            return ExpandFollowup(source=self._value(fields["from"]), each=self._emit_spec(fields["each"]))
        return StaticFollowup(emit=self._emit_spec(raw))

    def _pattern(self, items: _Items) -> Pattern:
        return Pattern(fields=tuple((key, self._predicate(value)) for key, value in items))

    def _predicate(self, raw: object) -> Predicate:
        self._count()
        items = _as_mapping(raw)
        if items is None:
            return EqualsPredicate(expected=self._literal(raw))
        keys = [key for key, _ in items]
        verbs = [key for key in keys if key in PREDICATE_VERBS]
        if len(verbs) > 1:
            raise RecipeCompileError(f"predicate has multiple verbs ({', '.join(verbs)}); use one verb per field")
        if len(verbs) == 1:
            verb = verbs[0]
            if len(keys) > 1:
                others = ", ".join(key for key in keys if key not in PREDICATE_VERBS)
                raise RecipeCompileError(f"predicate verb '{verb}' cannot be mixed with field keys ({others})")
            return self._verb(verb, dict(items)[verb])
        return ShapePredicate(nested=self._pattern(items))

    def _verb(self, verb: str, value: object) -> Predicate:
        match verb:
            case "equals":
                return EqualsPredicate(expected=self._literal(value))
            case "exists":
                return ExistsPredicate(should_exist=is_truthy(self._literal(value)))
            case "is":
                return IsPredicate(types=self._type_names(value))
            case "in":
                if not isinstance(value, list):
                    raise RecipeCompileError("'in:' must be an array")
                return InPredicate(values=tuple(self._literal(item) for item in value))
            case "shape":
                items = _as_mapping(value)
                if items is None:
                    raise RecipeCompileError("'shape:' must be a mapping")
                return ShapePredicate(nested=self._pattern(items))
            case "every":
                return EveryPredicate(element=self._predicate(value))
        raise RecipeCompileError(f"Unknown predicate verb '{verb}'")

    def _type_names(self, value: object) -> tuple[TypeName, ...]:
        names: list[TypeName] = []
        for candidate in value if isinstance(value, list) else [value]:
            # A bare YAML `null` inside `is: [...]` means the type name 'null'.
            name = "null" if candidate is None else candidate
            if not isinstance(name, str) or name not in TYPE_NAMES:
                raise RecipeCompileError(
                    f"'is:' must be a type or array of types, got {to_json_text(self._literal(candidate))}"
                )
            names.append(cast(TypeName, name))
        return tuple(names)

    def _emit_spec(self, raw: object) -> EmitSpec:
        self._count()
        items = _as_mapping(raw)
        if items is None:
            raise RecipeCompileError("emit must be a mapping")
        role: Expr | RoleTag | None = None
        content = tool_call = tool_calls = tool_call_id = spread = None
        for key, value in items:
            match key:
                case "role":
                    role = cast(RoleTag, value) if isinstance(value, str) and value in ROLE_TAGS else self._value(value)
                case "content":
                    content = self._value(value)
                case "toolCall":
                    tool_call = self._value(value)
                case "toolCalls":
                    tool_calls = self._value(value)
                case "toolCallId" | "tool_call_id":
                    tool_call_id = self._value(value)
                case "spread":
                    spread = self._value(value)
                case _:
                    raise RecipeCompileError(f"Unknown emit key '{key}'")
        return EmitSpec(
            role=role,
            content=content,
            tool_call=tool_call,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            spread=spread,
        )

    def _value(self, raw: object) -> Expr:
        self._count()
        if raw is None or isinstance(raw, bool | int | float):
            return LiteralExpr(value=raw)
        if isinstance(raw, str):
            return self._string(raw)
        if isinstance(raw, list):
            return ArrayExpr(items=tuple(self._value(item) for item in raw))
        items = _as_mapping(raw)
        if items is None:
            return LiteralExpr(value=self._literal(raw))
        if len(items) == 1:
            key, payload = items[0]
            if key in OPERATORS:
                return self._operator(key, payload)
            suggestion = nearest_operator(key, OPERATORS)
            if suggestion:
                raise RecipeCompileError(
                    f"Unknown operator '{key}'. Did you mean '{suggestion}'? "
                    "Wrap an intentional one-key object in 'literal:'."
                )
        return ObjectExpr(fields=tuple((key, self._value(value)) for key, value in items))

    def _literal(self, raw: object) -> Value:
        # A YAML scalar the frontend parser keeps as a string, such as a date, becomes that string here too.
        self._count()
        if raw is None or isinstance(raw, str | bool | int | float):
            return raw
        if isinstance(raw, list):
            return [self._literal(item) for item in raw]
        items = _as_mapping(raw)
        if items is not None:
            return {key: self._literal(value) for key, value in items}
        return str(raw)

    def _string(self, value: str) -> Expr:
        if value == "$":
            return SelfExpr()
        if _PATH.fullmatch(value):
            return PathExpr(segments=tuple(value[2:].split(".")))
        if _ROOTLESS_FIELD.match(value):
            raise RecipeCompileError(
                f"'{value}' is not a valid value expression. Use '$.{value[1:]}' for a field read, or '$' for the whole input."
            )
        if _INTERP.search(value):
            return self._interp(value)
        return LiteralExpr(value=value)

    def _interp(self, value: str) -> Expr:
        parts: list[str | Expr] = []
        cursor = 0
        for match in _INTERP.finditer(value):
            if match.start() > cursor:
                parts.append(value[cursor : match.start()])
            parts.append(PathExpr(segments=tuple(match.group(1).split("."))))
            cursor = match.end()
        if cursor < len(value):
            parts.append(value[cursor:])
        return InterpExpr(parts=tuple(parts))

    def _operator(self, operator: str, payload: object) -> Expr:
        match operator:
            case "literal":
                # Escape hatch for a one-key data object whose key collides with an operator name.
                return LiteralExpr(value=self._literal(payload))
            case "coalesce":
                return CoalesceExpr(source=self._coalesce_source(payload))
            case "try_parse_structured_content":
                return TryParseStructuredContentExpr(source=self._value(payload))
            case "stringify":
                return StringifyExpr(source=self._value(payload))
            case "join":
                args = self._operator_args(operator, payload)
                return JoinExpr(
                    source=self._required(args, "from"),
                    sep=self._optional(args, "sep"),
                    field=self._optional(args, "field"),
                )
            case "omit":
                args = self._operator_args(operator, payload)
                return OmitExpr(source=self._required(args, "from"), keys=self._optional(args, "keys"))
            case "select":
                args = self._operator_args(operator, payload)
                return SelectExpr(
                    source=self._required(args, "from"),
                    where=self._where(args.get("where", MISSING)),
                    pluck=self._pluck(args.get("pluck", MISSING)),
                    if_empty=self._optional(args, "if_empty"),
                )
            case "reject":
                args = self._operator_args(operator, payload)
                return RejectExpr(
                    source=self._required(args, "from"),
                    where=self._where(args.get("where", MISSING)),
                    if_empty=self._optional(args, "if_empty"),
                )
        raise RecipeCompileError(f"Unknown operator: {operator}")

    def _coalesce_source(self, payload: object) -> Expr:
        if isinstance(payload, list):
            return ArrayExpr(items=tuple(self._value(item) for item in payload))
        items = _as_mapping(payload)
        if items is None:
            raise RecipeCompileError("'coalesce:' takes an array or {from: [...]}")
        return self._required(dict(items), "from")

    def _operator_args(self, operator: str, payload: object) -> dict[str, object]:
        items = _as_mapping(payload)
        if items is None:
            raise RecipeCompileError(f"'{operator}:' takes a mapping")
        return dict(items)

    def _required(self, args: dict[str, object], key: str) -> Expr:
        if key not in args:
            raise RecipeCompileError(f"operator requires a '{key}:' argument")
        return self._value(args[key])

    def _optional(self, args: dict[str, object], key: str) -> Expr | None:
        return self._value(args[key]) if key in args else None

    def _where(self, raw: object) -> Pattern | None:
        if isinstance(raw, Missing):
            return None
        items = _as_mapping(raw)
        if items is None:
            raise RecipeCompileError("'where:' must be a mapping")
        return self._pattern(items)

    def _pluck(self, raw: object) -> Expr | None:
        if isinstance(raw, Missing):
            return None
        if isinstance(raw, str) and _BARE_FIELD.fullmatch(raw):
            return PathExpr(segments=(raw,))
        return self._value(raw)
