from enum import Enum

HOGQL_BYTECODE_IDENTIFIER_V0 = "_h"
HOGQL_BYTECODE_IDENTIFIER = "_H"
HOGQL_BYTECODE_FUNCTION = "_f"

# Version history:
#  0 - initial version
#  1 - added version numbers; reversed order of function args in stack
HOGQL_BYTECODE_VERSION = 1


class Operation(int, Enum):
    GET_GLOBAL = 1
    CALL_GLOBAL = 2
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
    POP = 35
    GET_LOCAL = 36
    SET_LOCAL = 37
    RETURN = 38
    JUMP = 39
    JUMP_IF_FALSE = 40
    DECLARE_FN = 41
    DICT = 42
    ARRAY = 43
    TUPLE = 44
    GET_PROPERTY = 45
    SET_PROPERTY = 46
    JUMP_IF_STACK_NOT_NULL = 47
    GET_PROPERTY_NULLISH = 48
    THROW = 49
    TRY = 50
    POP_TRY = 51
    CALLABLE = 52
    CLOSURE = 53
    CALL_LOCAL = 54
    GET_UPVALUE = 55
    SET_UPVALUE = 56
    CLOSE_UPVALUE = 57
