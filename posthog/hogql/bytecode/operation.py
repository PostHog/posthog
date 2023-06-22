from enum import Enum

from posthog.hogql.ast import CompareOperationOp, BinaryOperationOp

HOGQL_BYTECODE_IDENTIFIER = "_h"


class Operation(str, Enum):
    PLUS = BinaryOperationOp.Add
    MINUS = BinaryOperationOp.Sub
    MULTIPLY = BinaryOperationOp.Mult
    DIVIDE = BinaryOperationOp.Div
    MOD = BinaryOperationOp.Mod
    AND = "and"
    OR = "or"
    EQ = CompareOperationOp.Eq
    NOT_EQ = CompareOperationOp.NotEq
    GT = CompareOperationOp.Gt
    GT_EQ = CompareOperationOp.GtE
    LT = CompareOperationOp.Lt
    LT_EQ = CompareOperationOp.LtE
    LIKE = CompareOperationOp.Like
    ILIKE = CompareOperationOp.ILike
    NOT_LIKE = CompareOperationOp.NotLike
    NOT_ILIKE = CompareOperationOp.NotILike
    IN = CompareOperationOp.In
    NOT_IN = CompareOperationOp.NotIn
    REGEX = CompareOperationOp.Regex
    NOT_REGEX = CompareOperationOp.NotRegex
    NOT = "not"
    CONSTANT = ""
    CALL = "()"
    FIELD = "."
