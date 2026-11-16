from __future__ import annotations

import ast
import math
import operator
from collections.abc import Mapping
from enum import StrEnum
from typing import cast

from posthog.dataclasses import frozen

from products.ai_observability.backend.score_validation import validate_score_value

MAX_COMPOSITE_INPUTS = 16
MAX_FORMULA_LENGTH = 1024
MAX_FORMULA_NODES = 512
MAX_FORMULA_DEPTH = 16

type FormulaValue = float | bool | str | list[str]


class FormulaType(StrEnum):
    NUMBER = "numeric"
    BOOLEAN = "boolean"
    CATEGORIES = "categorical"
    STRING = "string"


class CompositeFormulaError(ValueError):
    pass


@frozen
class CompositeFormula:
    tree: ast.expr

    @classmethod
    def parse(cls, expression: str, inputs: Mapping[str, str], output_kind: str) -> CompositeFormula:
        if not expression or len(expression) > MAX_FORMULA_LENGTH:
            raise CompositeFormulaError(f"Provide a formula of 1 to {MAX_FORMULA_LENGTH} characters.")
        if not 1 <= len(inputs) <= MAX_COMPOSITE_INPUTS:
            raise CompositeFormulaError(f"Select 1 to {MAX_COMPOSITE_INPUTS} inputs.")
        try:
            tree = ast.parse(f"({expression}\n)", mode="eval").body
        except (SyntaxError, RecursionError, ValueError, MemoryError) as error:
            raise CompositeFormulaError("The formula is not a valid expression.") from error
        if sum(1 for _ in ast.walk(tree)) > MAX_FORMULA_NODES:
            raise CompositeFormulaError("The formula has too many operations.")
        formula = cls(tree=tree)
        inferred = formula._infer(tree, inputs, 0)
        if inferred != output_kind and not (inferred == FormulaType.STRING and output_kind == "categorical"):
            raise CompositeFormulaError(f"The formula must return a {output_kind} value.")
        used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in inputs}
        if used != inputs.keys():
            raise CompositeFormulaError("Every selected input must appear in the formula.")
        return formula

    def validate_output(self, kind: str, config: dict[str, object]) -> None:
        if kind != "categorical":
            return

        def validate(node: ast.expr) -> None:
            if isinstance(node, ast.IfExp):
                validate(node.body)
                validate(node.orelse)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                check([node.value])
            elif isinstance(node, ast.List):
                if all(isinstance(item, ast.Constant) for item in node.elts):
                    check([cast(str, cast(ast.Constant, item).value) for item in node.elts])

        def check(values: list[str]) -> None:
            errors = validate_score_value("categorical", config, categorical_values=values)
            if errors:
                raise CompositeFormulaError(next(iter(errors.values())))

        validate(self.tree)

    def _infer(self, node: ast.expr, inputs: Mapping[str, str], depth: int) -> FormulaType:
        if depth > MAX_FORMULA_DEPTH:
            raise CompositeFormulaError("The formula is nested too deeply.")

        def infer(child: ast.expr) -> FormulaType:
            return self._infer(child, inputs, depth + 1)

        match node:
            case ast.Constant(value=value) if isinstance(value, bool):
                return FormulaType.BOOLEAN
            case ast.Constant(value=value) if isinstance(value, int | float):
                try:
                    finite = math.isfinite(float(value))
                except OverflowError:
                    finite = False
                if finite:
                    return FormulaType.NUMBER
            case ast.Constant(value=value) if isinstance(value, str) and len(value) <= 128:
                return FormulaType.STRING
            case ast.Name(id=name) if name in inputs:
                return FormulaType(inputs[name])
            case ast.List(elts=elements) if elements and all(infer(item) == FormulaType.STRING for item in elements):
                return FormulaType.CATEGORIES
            case ast.BinOp(left=left, op=op, right=right) if isinstance(op, ast.Add | ast.Sub | ast.Mult | ast.Div):
                if infer(left) == infer(right) == FormulaType.NUMBER:
                    return FormulaType.NUMBER
                raise CompositeFormulaError("Arithmetic requires numbers. Use number(input) to convert a Boolean.")
            case ast.UnaryOp(op=op, operand=operand):
                if isinstance(op, ast.Not) and infer(operand) == FormulaType.BOOLEAN:
                    return FormulaType.BOOLEAN
                if isinstance(op, ast.UAdd | ast.USub) and infer(operand) == FormulaType.NUMBER:
                    return FormulaType.NUMBER
            case ast.BoolOp(op=op, values=values) if isinstance(op, ast.And | ast.Or):
                if all(infer(value) == FormulaType.BOOLEAN for value in values):
                    return FormulaType.BOOLEAN
                raise CompositeFormulaError("Use Boolean values or comparisons with and/or.")
            case ast.Compare(left=left, ops=ops, comparators=comparators):
                previous = infer(left)
                for comparison_op, comparator in zip(ops, comparators):
                    current = infer(comparator)
                    if isinstance(comparison_op, ast.In | ast.NotIn):
                        valid = previous == FormulaType.STRING and current == FormulaType.CATEGORIES
                    elif isinstance(comparison_op, ast.Eq | ast.NotEq):
                        valid = previous == current
                    else:
                        valid = (
                            isinstance(comparison_op, ast.Lt | ast.LtE | ast.Gt | ast.GtE)
                            and previous == current == FormulaType.NUMBER
                        )
                    if not valid:
                        raise CompositeFormulaError("The comparison uses incompatible values.")
                    previous = current
                return FormulaType.BOOLEAN
            case ast.IfExp(test=test, body=body, orelse=otherwise):
                condition_type = infer(test)
                result_type = infer(body)
                if condition_type == FormulaType.BOOLEAN and result_type == infer(otherwise):
                    return result_type
                raise CompositeFormulaError("A conditional needs a Boolean condition and matching result types.")
            case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in {"number", "min", "max", "abs"}:
                types = [infer(arg) for arg in args]
                if name == "number" and len(types) == 1 and types[0] in {FormulaType.NUMBER, FormulaType.BOOLEAN}:
                    return FormulaType.NUMBER
                if name == "abs" and types == [FormulaType.NUMBER]:
                    return FormulaType.NUMBER
                if (
                    name in {"min", "max"}
                    and 1 <= len(types) <= MAX_COMPOSITE_INPUTS
                    and all(kind == FormulaType.NUMBER for kind in types)
                ):
                    return FormulaType.NUMBER
                raise CompositeFormulaError(f"Invalid arguments for {name}().")
        raise CompositeFormulaError("Use input names, numbers, Boolean logic, comparisons, or supported functions.")

    def evaluate(self, inputs: Mapping[str, FormulaValue]) -> FormulaValue:
        try:
            return self._evaluate(self.tree, inputs)
        except (ArithmeticError, ValueError, TypeError, KeyError) as error:
            raise CompositeFormulaError("The formula could not produce a valid value for these inputs.") from error

    def _evaluate(self, node: ast.expr, inputs: Mapping[str, FormulaValue]) -> FormulaValue:
        def evaluate(child: ast.expr) -> FormulaValue:
            return self._evaluate(child, inputs)

        match node:
            case ast.Constant(value=value) if isinstance(value, bool | str):
                return value
            case ast.Constant(value=value) if isinstance(value, int | float):
                return float(value)
            case ast.Name(id=name):
                return inputs[name]
            case ast.List(elts=elements):
                return [cast(str, evaluate(item)) for item in elements]
            case ast.BinOp(left=left, op=op, right=right):
                operations = {
                    ast.Add: operator.add,
                    ast.Sub: operator.sub,
                    ast.Mult: operator.mul,
                    ast.Div: operator.truediv,
                }
                value = operations[type(op)](cast(float, evaluate(left)), cast(float, evaluate(right)))
                if not math.isfinite(value):
                    raise CompositeFormulaError("The formula produced a non-finite number.")
                return float(f"{value:.12g}")
            case ast.UnaryOp(op=ast.Not(), operand=operand):
                return not evaluate(operand)
            case ast.UnaryOp(op=op, operand=operand):
                value = cast(float, evaluate(operand))
                return -value if isinstance(op, ast.USub) else value
            case ast.BoolOp(op=ast.And(), values=values):
                return all(evaluate(value) for value in values)
            case ast.BoolOp(op=ast.Or(), values=values):
                return any(evaluate(value) for value in values)
            case ast.Compare(left=left, ops=ops, comparators=comparators):
                previous = evaluate(left)
                for comparison_op, comparator in zip(ops, comparators):
                    current = evaluate(comparator)
                    if isinstance(comparison_op, ast.In | ast.NotIn):
                        matches = cast(str, previous) in cast(list[str], current)
                        matches = not matches if isinstance(comparison_op, ast.NotIn) else matches
                    else:
                        comparisons = {
                            ast.Eq: operator.eq,
                            ast.NotEq: operator.ne,
                            ast.Lt: operator.lt,
                            ast.LtE: operator.le,
                            ast.Gt: operator.gt,
                            ast.GtE: operator.ge,
                        }
                        matches = comparisons[type(comparison_op)](previous, current)
                    if not matches:
                        return False
                    previous = current
                return True
            case ast.IfExp(test=test, body=body, orelse=otherwise):
                return evaluate(body if evaluate(test) else otherwise)
            case ast.Call(func=ast.Name(id=name), args=args):
                arguments = [cast(float, evaluate(arg)) for arg in args]
                if name == "number":
                    return float(arguments[0])
                if name == "abs":
                    return abs(arguments[0])
                return min(arguments) if name == "min" else max(arguments)
        raise CompositeFormulaError("Unsupported formula operation.")
