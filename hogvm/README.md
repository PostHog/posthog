# HogVM

A HogVM is a 🦔 that runs HogQL bytecode. It's purpose is to locally evaluate HogQL expressions against any object.

## HogQL bytecode

HogQL Bytecode is a compact representation of a subset of the HogQL AST nodes. It follows a certain structure:

```
1 + 2                  # [_H, op.INTEGER, 2, op.INTEGER, 1, op.PLUS]
1 and 2                # [_H, op.INTEGER, 2, op.INTEGER, 1, op.AND, 2]
1 or 2                 # [_H, op.INTEGER, 2, op.INTEGER, 1, op.OR, 2]
not true               # [_H, op.TRUE, op.NOT]
properties.bla         # [_H, op.STRING, "bla", op.STRING, "properties", op.GET_GLOBAL, 2]
call('arg', 'another') # [_H, op.STRING, "another", op.STRING, "arg", op.CALL, "call", 2]
1 = 2                  # [_H, op.INTEGER, 2, op.INTEGER, 1, op.EQ]
'bla' !~ 'a'           # [_H, op.STRING, 'a', op.STRING, 'bla', op.NOT_REGEX]
```

## Compliant implementation

The `python/execute.py` function in this folder acts as the reference implementation in case of disputes.

### Operations

To be considered a PostHog HogQL Bytecode Certified Parser, you must implement the following operations:

```bash
FIELD = 1          # [arg3, arg2, arg1, FIELD, 3]       # arg1.arg2.arg3
CALL = 2           # [arg2, arg1, CALL, 'concat', 2]    # concat(arg1, arg2)
AND = 3            # [val3, val2, val1, AND, 3]         # val1 and val2 and val3
OR = 4             # [val3, val2, val1, OR, 3]          # val1 or val2 or val3
NOT = 5            # [val, NOT]                         # not val
PLUS = 6           # [val2, val1, PLUS]                 # val1 + val2
MINUS = 7          # [val2, val1, MINUS]                # val1 - val2
MULTIPLY = 8       # [val2, val1, MULTIPLY]             # val1 * val2
DIVIDE = 9         # [val2, val1, DIVIDE]               # val1 / val2
MOD = 10           # [val2, val1, MOD]                  # val1 % val2
EQ = 11            # [val2, val1, EQ]                   # val1 == val2
NOT_EQ = 12        # [val2, val1, NOT_EQ]               # val1 != val2
GT = 13            # [val2, val1, GT]                   # val1 > val2
GT_EQ = 14         # [val2, val1, GT_EQ]                # val1 >= val2
LT = 15            # [val2, val1, LT]                   # val1 < val2
LT_EQ = 16         # [val2, val1, LT_EQ]                # val1 <= val2
LIKE = 17          # [val2, val1, LIKE]                 # val1 like val2
ILIKE = 18         # [val2, val1, ILIKE]                # val1 ilike val2
NOT_LIKE = 19      # [val2, val1, NOT_LIKE]             # val1 not like val2
NOT_ILIKE = 20     # [val2, val1, NOT_ILIKE]            # val1 not ilike val2
IN = 21            # [val2, val1, IN]                   # val1 in val2
NOT_IN = 22        # [val2, val1, NOT_IN]               # val1 not in val2
REGEX = 23         # [val2, val1, REGEX]                # val1 =~ val2
NOT_REGEX = 24     # [val2, val1, NOT_REGEX]            # val1 !~ val2
IREGEX = 25        # [val2, val1, IREGEX]               # val1 =~* val2
NOT_IREGEX = 26    # [val2, val1, NOT_IREGEX]           # val1 !~* val2
TRUE = 29          # [TRUE]                             # true
FALSE = 30         # [FALSE]                            # false
NULL = 31          # [NULL]                             # null
STRING = 32        # [STRING, 'text']                   # 'text'
INTEGER = 33       # [INTEGER, 123]                     # 123
FLOAT = 34         # [FLOAT, 123.12]                    # 123.01
```

### Async Operations

Some operations can't be computed directly, and are thus asked back to the caller. These include:

```bash
IN_COHORT = 27     # [val2, val1, IREGEX]               # val1 in cohort val2
NOT_IN_COHORT = 28 # [val2, val1, NOT_IREGEX]           # val1 not in cohort val2
```

The arguments for these instructions will be passed on to the provided `async_operation(*args)` in reverse:

```python
def async_operation(*args):
    if args[0] == op.IN_COHORT:
        return db.queryInCohort(args[1], args[2])
    return False

execute_bytecode(to_bytecode("'user_id' in cohort 2"), {}, async_operation).result
```

### Functions

A PostHog HogQL Bytecode Certified Parser must also implement the following function calls:

```bash
concat(...)              # concat('test: ', 1, null, '!') == 'test: 1!'
match(string, pattern)   # match('fish', '$fi.*') == true
toString(val)            # toString(true) == 'true'
toInt(val)               # toInt('123') == 123
toFloat(val)             # toFloat('123.2') == 123.2
toUUID(val)              # toUUID('string') == 'string'
ifNull(val, alternative) # ifNull('string', false) == 'string'
```

### Null handling

In HogQL equality comparisons, `null` is treated as any other variable. Its presence will not make functions automatically return `null`, as is the ClickHouse default.

```sql
1 == null # false
1 != null # true
```

Nulls are just ignored in `concat`


## Known broken features

- **Regular Expression** support is implemented, but NOT GUARANTEED to the same way across platforms. Different implementations (ClickHouse, Python, Node) use different Regexp engines. ClickHouse uses `re2`, the others use `pcre`. Use the case-insensitive regex operators instead of passing in modifier flags through the expression.
- **DateTime** comparisons are not supported.
- **Cohort Matching** operations are not implemented.
- Only a small subset of functions is enabled. This list is bound to expand.
