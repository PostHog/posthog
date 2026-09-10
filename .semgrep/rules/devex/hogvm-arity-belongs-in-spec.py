# Test cases for the hogvm-arity-belongs-in-spec-python rule.
# ruff: noqa: F821
# ruleid: hogvm-arity-belongs-in-spec-python
_bad_min = STLFunction(fn=lower, minArgs=1)

# ruleid: hogvm-arity-belongs-in-spec-python
_bad_max = STLFunction(fn=lower, maxArgs=2)

# ruleid: hogvm-arity-belongs-in-spec-python
_bad_both = STLFunction(fn=lower, minArgs=1, maxArgs=2, is_blocking=True)

# ok: hogvm-arity-belongs-in-spec-python
_ok = STLFunction(fn=lower)

# ok: hogvm-arity-belongs-in-spec-python
_ok_blocking = STLFunction(fn=sleep, is_blocking=True)
