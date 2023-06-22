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
PLUS = "+"              # [val2, val1, '+']
MINUS = "-"             # [val2, val1, '-']
MULTIPLY = "*"          # [val2, val1, '*']
DIVIDE = "/"            # [val2, val1, '/']
MOD = "%"               # [val2, val1, '%']
AND = "and"             # [val3, val2, val1, 'and', 3]
OR = "or"               # [val3, val2, val1, 'or', 3]
EQ = "=="               # [val2, val1, '==']
NOT_EQ = "!="           # [val2, val1, '!=']
GT = ">"                # [val2, val1, '>']
GT_EQ = ">="            # [val2, val1, '>=']
LT = "<"                # [val2, val1, '<']
LT_EQ = "<="            # [val2, val1, '<=']
LIKE = "like"           # [val2, val1, 'like']
ILIKE = "ilike"         # [val2, val1, 'ilike']
NOT_LIKE = "not like"   # [val2, val1, 'not like']
NOT_ILIKE = "not ilike" # [val2, val1, 'not ilike']
IN = "in"               # [val2, val1, 'in']
NOT_IN = "not in"       # [val2, val1, 'not in']
REGEX = "=~"            # [val2, val1, '=!']
NOT_REGEX = "!~"        # [val2, val1, '!=']
NOT = "not"             # [val, 'not']
CONSTANT = ""           # ['', constant]
CALL = "()"             # [arg2, arg1, '()', 'concat', 2]
FIELD = "."             # [arg3, arg2, arg1, '.', 3]
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
