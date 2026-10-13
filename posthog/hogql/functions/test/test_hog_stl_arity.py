from django.test import SimpleTestCase

from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS

from common.hogvm.python.stl import STL

HOGQL_FUNCTIONS = {**HOGQL_CLICKHOUSE_FUNCTIONS, **HOGQL_POSTHOG_FUNCTIONS}

HIGHER_MIN_ARGS_THAN_HOGQL = {
    "dateAdd": "Hog requires unit, amount, and datetime; it does not implement HogQL's date/interval overload",
    "toTimeZone": "Hog has no implicit project timezone, so the timezone argument is required",
}

LOWER_MAX_ARGS_THAN_HOGQL = {
    "range": "HogQL takes a step argument, Hog's implementation has no step and would ignore it",
}


class TestHogStlArity(SimpleTestCase):
    def test_no_builtin_accepts_fewer_arguments_than_hogql(self) -> None:
        too_strict = []
        for name, stl_fn in STL.items():
            hogql_fn = HOGQL_FUNCTIONS.get(name)
            if hogql_fn is None:
                continue
            if (stl_fn.minArgs or 0) > hogql_fn.min_args and name not in HIGHER_MIN_ARGS_THAN_HOGQL:
                too_strict.append(f"{name}: Hog minArgs={stl_fn.minArgs}, HogQL accepts {hogql_fn.min_args}")
            if (
                stl_fn.maxArgs is not None
                and name not in LOWER_MAX_ARGS_THAN_HOGQL
                and (hogql_fn.max_args is None or hogql_fn.max_args > stl_fn.maxArgs)
            ):
                limit = "unbounded" if hogql_fn.max_args is None else hogql_fn.max_args
                too_strict.append(f"{name}: Hog maxArgs={stl_fn.maxArgs}, HogQL accepts {limit}")

        assert too_strict == []
