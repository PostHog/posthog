import ast
import operator
from typing import Any


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
            result = self._evaluate(node.lower(), map)
            res.append(result)
        return res

    def _evaluate(self, node, const_map: dict[str, Any]):
        if isinstance(node, list | tuple):
            return [self._evaluate(sub_node, const_map) for sub_node in node]

        elif isinstance(node, str):
            return self._evaluate(ast.parse(node), const_map)

        elif isinstance(node, ast.Module):
            values = []
            for body in node.body:
                values.append(self._evaluate(body, const_map))
            if len(values) == 1:
                values = values[0]
            return values

        elif isinstance(node, ast.Expr):
            return self._evaluate(node.value, const_map)

        elif isinstance(node, ast.BinOp):
            left = self._evaluate(node.left, const_map)
            op = node.op
            right = self._evaluate(node.right, const_map)
            try:
                return self.op_map[type(op)](left, right)
            except ZeroDivisionError:
                return 0
            except KeyError:
                raise ValueError(f"Operator {op.__class__.__name__} not supported")

        elif isinstance(node, ast.UnaryOp):
            operand = self._evaluate(node.operand, const_map)
            unary_op = node.op
            if isinstance(unary_op, ast.USub):
                return -operand
            elif isinstance(unary_op, ast.UAdd):
                return operand
            raise ValueError(f"Operator {unary_op.__class__.__name__} not supported")

        elif isinstance(node, ast.Num):
            return node.n

        elif isinstance(node, ast.Name):
            try:
                return const_map[node.id]
            except KeyError:
                raise ValueError(f"Constant {node.id} not supported")

        raise TypeError(f"Unsupported operation: {node.__class__.__name__}")
