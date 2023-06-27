from enum import Enum

HOGQL_BYTECODE_IDENTIFIER = "_h"


class Operation(str, Enum):
    FIELD = 1
    CALL = 2
    AND = 3
    OR = 4
    NOT = 5
    PLUS = 6
    MINUS = 7
    MULTIPLY = 8
    DIVIDE = 9
    MOD = 10
    EQ = 11
    NOT_EQ = 12
    GT = 13
    GT_EQ = 14
    LT = 15
    LT_EQ = 16
    LIKE = 17
    ILIKE = 18
    NOT_LIKE = 19
    NOT_ILIKE = 20
    IN = 21
    NOT_IN = 22
    REGEX = 23
    NOT_REGEX = 24
    TRUE = 25
    FALSE = 26
    NULL = 27
    STRING = 28
    INTEGER = 29
    FLOAT = 30
