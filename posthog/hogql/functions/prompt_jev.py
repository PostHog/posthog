from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.llm.system_one import ChoiceQuestion, NoulQuestion, Question

MAX_CHOICES = 16
# jev is decide with the jeeves model, so both names share one parser and one executor.
DECISION_FUNCTIONS = frozenset({"jev", "decide"})
DECIDE_MODELS = ("jeeves", "jevk5")


def is_decision_call(name: str) -> bool:
    return name.lower() in DECISION_FUNCTIONS


CHOICE_TYPE = "Tuple(choice Nullable(String), probabilities Array(Tuple(value String, probability Float64)), confidence Nullable(Float64))"


class PromptJevFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_call(self, node: ast.Call) -> None:
        if is_decision_call(node.name):
            self.calls.append(node)
        super().visit_call(node)

    @classmethod
    def contains(cls, node: ast.AST) -> bool:
        finder = cls()
        finder.visit(node)
        return bool(finder.calls)


@frozen
class PromptJevCall:
    input: ast.Expr
    question: Question
    batch_size: int
    model: str

    @property
    def clickhouse_type(self) -> str:
        return CHOICE_TYPE if isinstance(self.question, ChoiceQuestion) else "Nullable(Float64)"

    @classmethod
    def parse(cls, node: ast.Call) -> "PromptJevCall":
        name = node.name.lower()
        if node.params or node.distinct or node.filter_expr or node.order_by or node.within_group:
            raise QueryError(f"{name} does not accept aggregate modifiers.")
        if len(node.args) < 2 or isinstance(node.args[0], ast.NamedArgument):
            raise QueryError(f"Use {name}(input, instructions, choice := ['label', 'other']).")
        instructions = _parse_instructions(name, node.args[1])
        options = _parse_options(name, node.args[2:])
        model = options.get("model", ast.Constant(value="jeeves"))
        if not isinstance(model, ast.Constant) or model.value not in DECIDE_MODELS:
            raise QueryError(f"{name} model must be one of: {', '.join(repr(m) for m in DECIDE_MODELS)}.")
        batch = options.get("batch_size", ast.Constant(value=16))
        if not isinstance(batch, ast.Constant) or type(batch.value) is not int or not 1 <= batch.value <= 32:
            raise QueryError(f"{name} batch_size must be an integer literal between 1 and 32.")
        question = _parse_question(name, instructions, options)
        if PromptJevFinder.contains(node.args[0]):
            raise QueryError(f"Put each {name} evaluation in a separate subquery.")
        return cls(input=node.args[0], question=question, batch_size=batch.value, model=model.value)


def _parse_instructions(name: str, instructions: ast.Expr) -> str:
    if (
        not isinstance(instructions, ast.Constant)
        or not isinstance(instructions.value, str)
        or not instructions.value.strip()
    ):
        raise QueryError(f"{name} instructions must be a non-empty string literal.")
    if len(instructions.value.encode()) > 8192:
        raise QueryError(f"{name} instructions exceed 8 KiB. Shorten the instructions.")
    return instructions.value


def _parse_options(name: str, args: list[ast.Expr]) -> dict[str, ast.Expr]:
    allowed = {"choice", "noul", "batch_size"} | ({"model"} if name == "decide" else set())
    options: dict[str, ast.Expr] = {}
    for arg in args:
        if not isinstance(arg, ast.NamedArgument) or arg.name not in allowed:
            raise QueryError(f"{name} supports the named arguments {', '.join(sorted(allowed))}.")
        if arg.name in options:
            raise QueryError(f"{name} received {arg.name} more than once.")
        options[arg.name] = arg.value
    if "choice" in options and "noul" in options:
        raise QueryError(f"Use either choice or noul with {name}.")
    return options


def _parse_labels(name: str, option: ast.Expr | None) -> dict[str, str | None]:
    criteria: dict[str, str | None] = {}
    if option is None:
        return criteria
    if not isinstance(option, ast.Array):
        raise QueryError(f"{name} criteria must be an array of string literals.")
    for item in option.exprs:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str) or not item.value.strip():
            raise QueryError(f"{name} criteria must contain non-empty string literals.")
        if item.value in criteria:
            raise QueryError(f"{name} criteria must be unique.")
        if len(item.value.encode()) > 1024:
            raise QueryError(f"{name} labels exceed 1 KiB. Shorten the labels.")
        criteria[item.value] = None
    return criteria


def _parse_question(name: str, instructions: str, options: dict[str, ast.Expr]) -> Question:
    criteria = _parse_labels(name, options.get("choice", options.get("noul")))
    if "choice" in options:
        if not 2 <= len(criteria) <= MAX_CHOICES:
            raise QueryError(f"{name} choice needs between 2 and {MAX_CHOICES} labels.")
        return ChoiceQuestion(instructions=instructions, criteria=criteria)
    if "noul" in options and set(criteria) != {"true", "false"}:
        raise QueryError(f"{name} noul needs exactly the labels 'true' and 'false'.")
    return NoulQuestion(instructions=instructions)
