# HogQL bytecode format

You can use the HogQL "bytecode" format to quickly evaluate HogQL expressions locally.

## Examples

```
to_bytecode("1 + 2") == ["_h", "", 2, "", 1, "+"]
to_bytecode("1 and 2") == ["_h", "", 2, "", 1, "and", 2]
to_bytecode("1 or 2") == ["_h", "", 2, "", 1, "or", 2]
to_bytecode("not true") == ["_h", "", True, "not"]
to_bytecode("properties.bla") == ["_h", "", "bla", "", "properties", ".", 2]
to_bytecode("call('arg', 'another')") == ["_h", "", "another", "", "arg", "()", "call", 2]
to_bytecode("1 = 2") == ["_h", "", 2, "", 1, "=="]
to_bytecode("1 == 2") == ["_h", "", 2, "", 1, "=="]
```

## Reference implementation

The `execute.py` function in this folder acts as the reference implementation.

To be considered a PostHog HogQL Bytecode Certified Parser, you must implement the following operations:

```bash
FIELD = 1         # [arg3, arg2, arg1, FIELD, 3]       # arg1.arg2.arg3
CALL = 2          # [arg2, arg1, CALL, 'concat', 2]    # concat(arg1, arg2)
AND = 3           # [val3, val2, val1, AND, 3]         # val1 and val2 and val3
OR = 4            # [val3, val2, val1, OR, 3]          # val1 or val2 or val3
NOT = 5           # [val, NOT]                         # not val
PLUS = 6          # [val2, val1, PLUS]                 # val1 + val2
MINUS = 7         # [val2, val1, MINUS]                # val1 - val2
MULTIPLY = 8      # [val2, val1, MULTIPLY]             # val1 * val2
DIVIDE = 9        # [val2, val1, DIVIDE]               # val1 / val2
MOD = 10          # [val2, val1, MOD]                  # val1 % val2
EQ = 11           # [val2, val1, EQ]                   # val1 == val2
NOT_EQ = 12       # [val2, val1, NOT_EQ]               # val1 != val2
GT = 13           # [val2, val1, GT]                   # val1 > val2
GT_EQ = 14        # [val2, val1, GT_EQ]                # val1 >= val2
LT = 15           # [val2, val1, LT]                   # val1 < val2
LT_EQ = 16        # [val2, val1, LT_EQ]                # val1 <= val2
LIKE = 17         # [val2, val1, LIKE]                 # val1 like val2
ILIKE = 18        # [val2, val1, ILIKE]                # val1 ilike val2
NOT_LIKE = 19     # [val2, val1, NOT_LIKE]             # val1 not like val2
NOT_ILIKE = 20    # [val2, val1, NOT_ILIKE]            # val1 not ilike val2
IN = 21           # [val2, val1, IN]                   # val1 in val2
NOT_IN = 22       # [val2, val1, NOT_IN]               # val1 not in val2
REGEX = 23        # [val2, val1, REGEX]                # val1 =~ val2
NOT_REGEX = 24    # [val2, val1, NOT_REGEX]            # val1 !~ val2
TRUE = 25         # [TRUE]                             # true
FALSE = 26        # [FALSE]                            # false
NULL = 27         # [NULL]                             # null
STRING = 28       # [STRING, 'text']                   # 'text'
INTEGER = 29      # [INTEGER, 123]                     # 123
FLOAT = 30        # [FLOAT, 123.12]                    # 123.01
```

You must also implement the following function calls:

```bash
concat(...)             # concat('test: ', 1, null, '!') == 'test: 1!'
match(string, pattern)  # match('fish', '$fi.*') == true
toString(val)           # toString(true) == 'true'
toInt(val)              # toInt('123') == 123
toFloat(val)            # toFloat('123.2') == 123.2
toUUID(val)             # toUUID('string') == 'string'
```

## Notable missing features

- As of now, there is no support for `DateTime` comparisons.
