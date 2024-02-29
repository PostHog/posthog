from enum import Enum

HOGQL_BYTECODE_IDENTIFIER = "_h"


SUPPORTED_FUNCTIONS = ("concat", "match", "toString", "toInt", "toFloat", "toUUID", "ifNull")


class Operation(int, Enum):
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
    IREGEX = 25
    NOT_IREGEX = 26
    IN_COHORT = 27
    NOT_IN_COHORT = 28
    TRUE = 29
    FALSE = 30
    NULL = 31
    STRING = 32
    INTEGER = 33
    FLOAT = 34
