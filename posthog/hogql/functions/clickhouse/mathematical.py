from ..core import HogQLFunctionMeta

# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
MATHEMATICAL_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "e": HogQLFunctionMeta("e"),
    "pi": HogQLFunctionMeta("pi"),
    "exp": HogQLFunctionMeta("exp", 1, 1, case_sensitive=False),
    "log": HogQLFunctionMeta("log", 1, 1, case_sensitive=False),
    "ln": HogQLFunctionMeta("ln", 1, 1, case_sensitive=False),
    "exp2": HogQLFunctionMeta("exp2", 1, 1),
    "log2": HogQLFunctionMeta("log2", 1, 1, case_sensitive=False),
    "exp10": HogQLFunctionMeta("exp10", 1, 1),
    "log10": HogQLFunctionMeta("log10", 1, 1, case_sensitive=False),
    "sqrt": HogQLFunctionMeta("sqrt", 1, 1, case_sensitive=False),
    "cbrt": HogQLFunctionMeta("cbrt", 1, 1),
    "erf": HogQLFunctionMeta("erf", 1, 1),
    "erfc": HogQLFunctionMeta("erfc", 1, 1),
    "lgamma": HogQLFunctionMeta("lgamma", 1, 1),
    "tgamma": HogQLFunctionMeta("tgamma", 1, 1),
    "sin": HogQLFunctionMeta("sin", 1, 1, case_sensitive=False),
    "cos": HogQLFunctionMeta("cos", 1, 1, case_sensitive=False),
    "tan": HogQLFunctionMeta("tan", 1, 1, case_sensitive=False),
    "asin": HogQLFunctionMeta("asin", 1, 1, case_sensitive=False),
    "acos": HogQLFunctionMeta("acos", 1, 1, case_sensitive=False),
    "atan": HogQLFunctionMeta("atan", 1, 1, case_sensitive=False),
    "pow": HogQLFunctionMeta("pow", 2, 2, case_sensitive=False),
    "power": HogQLFunctionMeta("power", 2, 2, case_sensitive=False),
    "intExp2": HogQLFunctionMeta("intExp2", 1, 1),
    "intExp10": HogQLFunctionMeta("intExp10", 1, 1),
    "cosh": HogQLFunctionMeta("cosh", 1, 1),
    "acosh": HogQLFunctionMeta("acosh", 1, 1),
    "sinh": HogQLFunctionMeta("sinh", 1, 1),
    "asinh": HogQLFunctionMeta("asinh", 1, 1),
    "atanh": HogQLFunctionMeta("atanh", 1, 1),
    "atan2": HogQLFunctionMeta("atan2", 2, 2),
    "hypot": HogQLFunctionMeta("hypot", 2, 2),
    "log1p": HogQLFunctionMeta("log1p", 1, 1),
    "sign": HogQLFunctionMeta("sign", 1, 1, case_sensitive=False),
    "degrees": HogQLFunctionMeta("degrees", 1, 1, case_sensitive=False),
    "radians": HogQLFunctionMeta("radians", 1, 1, case_sensitive=False),
    "factorial": HogQLFunctionMeta("factorial", 1, 1, case_sensitive=False),
    "width_bucket": HogQLFunctionMeta("width_bucket", 4, 4),
}

# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
ROUNDING_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "floor": HogQLFunctionMeta("floor", 1, 2, case_sensitive=False),
    "ceil": HogQLFunctionMeta("ceil", 1, 2, case_sensitive=False),
    "trunc": HogQLFunctionMeta("trunc", 1, 2, case_sensitive=False),
    "round": HogQLFunctionMeta("round", 1, 2, case_sensitive=False),
    "roundBankers": HogQLFunctionMeta("roundBankers", 1, 2),
    "roundToExp2": HogQLFunctionMeta("roundToExp2", 1, 1),
    "roundDuration": HogQLFunctionMeta("roundDuration", 1, 1),
    "roundAge": HogQLFunctionMeta("roundAge", 1, 1),
    "roundDown": HogQLFunctionMeta("roundDown", 2, 2),
}

# Combined mathematical functions
MATH_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **MATHEMATICAL_FUNCTIONS,
    **ROUNDING_FUNCTIONS,
}
