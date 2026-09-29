from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.llm.system_one import ChoiceQuestion, NoulQuestion, Question

MODEL = "posthog/hogference/jevk5-fp8-0.2"
MAX_CHOICES = 16
CHOICE_TYPE = "Tuple(choice Nullable(String), probabilities Array(Tuple(value String, probability Float64)), confidence Nullable(Float64))"


class PromptJevFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower() == "promptjev":
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

    @property
    def clickhouse_type(self) -> str:
        return CHOICE_TYPE if isinstance(self.question, ChoiceQuestion) else "Nullable(Float64)"

    @classmethod
    def parse(cls, node: ast.Call) -> "PromptJevCall":
        if node.params or node.distinct or node.filter_expr or node.order_by or node.within_group:
            raise QueryError("promptJev does not accept aggregate modifiers.")
        if len(node.args) < 2 or isinstance(node.args[0], ast.NamedArgument):
            raise QueryError("Use promptJev(input, instructions, choice := ['label', 'other']).")
        instructions = node.args[1]
        if (
            not isinstance(instructions, ast.Constant)
            or not isinstance(instructions.value, str)
            or not instructions.value.strip()
        ):
            raise QueryError("promptJev instructions must be a non-empty string literal.")
        if len(instructions.value.encode()) > 8192:
            raise QueryError("promptJev instructions exceed 8 KiB. Shorten the instructions.")
        options: dict[str, ast.Expr] = {}
        for arg in node.args[2:]:
            if not isinstance(arg, ast.NamedArgument) or arg.name not in {"choice", "noul", "batch_size"}:
                raise QueryError("promptJev supports the named arguments choice, noul, and batch_size.")
            if arg.name in options:
                raise QueryError(f"promptJev received {arg.name} more than once.")
            options[arg.name] = arg.value
        if "choice" in options and "noul" in options:
            raise QueryError("Use either choice or noul with promptJev.")
        batch = options.get("batch_size", ast.Constant(value=16))
        if not isinstance(batch, ast.Constant) or type(batch.value) is not int or not 1 <= batch.value <= 32:
            raise QueryError("promptJev batch_size must be an integer literal between 1 and 32.")
        criteria: dict[str, str | None] = {}
        option = options.get("choice", options.get("noul"))
        if option is not None:
            if not isinstance(option, ast.Array):
                raise QueryError("promptJev criteria must be an array of string literals.")
            for item in option.exprs:
                if not isinstance(item, ast.Constant) or not isinstance(item.value, str) or not item.value.strip():
                    raise QueryError("promptJev criteria must contain non-empty string literals.")
                if item.value in criteria:
                    raise QueryError("promptJev criteria must be unique.")
                if len(item.value.encode()) > 1024:
                    raise QueryError("promptJev labels exceed 1 KiB. Shorten the labels.")
                criteria[item.value] = None
        if "choice" in options:
            if not 2 <= len(criteria) <= MAX_CHOICES:
                raise QueryError(f"promptJev choice needs between 2 and {MAX_CHOICES} labels.")
            question: Question = ChoiceQuestion(instructions=instructions.value, criteria=criteria)
        else:
            if "noul" in options and set(criteria) != {"true", "false"}:
                raise QueryError("promptJev noul needs exactly the labels 'true' and 'false'.")
            question = NoulQuestion(instructions=instructions.value)
        if PromptJevFinder.contains(node.args[0]):
            raise QueryError("Put each promptJev evaluation in a separate subquery.")
        return cls(input=node.args[0], question=question, batch_size=batch.value)
