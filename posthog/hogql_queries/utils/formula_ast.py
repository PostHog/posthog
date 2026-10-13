import ast
import operator
from typing import Any

from posthog.hogql.errors import ExposedHogQLError


class FormulaAST:
    op_map = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    zipped_data: list[tuple[float]]

    def __init__(self, data: list[list[float]]):
        self.zipped_data = list(zip(*data))

    def call(self, node: str):
        res = []
        for consts in self.zipped_data:
            map = {}
            for index, value in enumerate(consts):
                map[chr(ord("`") + index + 1)] = value
            result = self._evaluate(node.strip().lower(), map)
            res.append(result)
        return res

    def _evaluate(self, node, const_map: dict[str, Any]):
        match node:
            case list() | tuple():
                return [self._evaluate(sub_node, const_map) for sub_node in node]

            case str():
                return self._evaluate(ast.parse(node), const_map)

            case ast.Module(body=body):
                values = []
                for sub_node in body:
                    values.append(self._evaluate(sub_node, const_map))
                if len(values) == 1:
                    values = values[0]
                return values

            case ast.Expr(value=value):
                return self._evaluate(value, const_map)

            case ast.BinOp(left=left_node, op=op, right=right_node):
                left = self._evaluate(left_node, const_map)
                right = self._evaluate(right_node, const_map)
                # Handle None values that may come from empty query results
                if left is None:
                    left = 0
                if right is None:
                    right = 0
                try:
                    return self.op_map[type(op)](left, right)
                except ZeroDivisionError:
                    return 0
                except KeyError:
                    raise ExposedHogQLError(
                        f"Formulas only support arithmetic ( + - * / % ** ) between series, not {op.__class__.__name__}"
                    )

            case ast.UnaryOp(op=unary_op, operand=operand_node):
                operand = self._evaluate(operand_node, const_map)
                # Handle None values that may come from empty query results
                if operand is None:
                    operand = 0
                if isinstance(unary_op, ast.USub):
                    return -operand
                elif isinstance(unary_op, ast.UAdd):
                    return operand
                raise ExposedHogQLError(
                    f"Formulas only support arithmetic ( + - * / % ** ) between series, not {unary_op.__class__.__name__}"
                )

            case ast.Constant(value=int() | float() as value) if not isinstance(value, bool):
                return value

            case ast.Name(id=name):
                try:
                    return const_map[name]
                except KeyError:
                    available = sorted(k.upper() for k in const_map if k.isalpha() and len(k) == 1)
                    series_word = "series is" if len(available) == 1 else "series are"
                    raise ExposedHogQLError(
                        f"Formula references series {name.upper()}, "
                        f"but only {len(available)} {series_word} defined ({', '.join(available) or 'none'})"
                    )

            case ast.Call(func=func):
                called = f"{func.id.upper()}()" if isinstance(func, ast.Name) else "function calls"
                raise ExposedHogQLError(
                    f"Formulas only support arithmetic between series (like (A + B) / 2), not {called}. "
                    f"To aggregate a series, set its measurement (for example median or p95) on the series itself."
                )

            case _:
                raise ExposedHogQLError(
                    f"Formulas only support arithmetic between series, not {node.__class__.__name__}"
                )
