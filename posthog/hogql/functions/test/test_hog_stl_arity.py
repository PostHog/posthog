from django.test import SimpleTestCase

from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS

from common.hogvm.python.stl import STL

HOGQL_FUNCTIONS = {**HOGQL_CLICKHOUSE_FUNCTIONS, **HOGQL_POSTHOG_FUNCTIONS}

# Hog builtins that stay stricter than HogQL on purpose, with the reason.
NARROWER_THAN_HOGQL_ON_PURPOSE = {
    "range": "HogQL takes a step argument, Hog's implementation has no step and would ignore it",
}


class TestHogStlArity(SimpleTestCase):
    def test_no_builtin_accepts_fewer_arguments_than_hogql(self):
        # A name that HogQL and Hog share reads as one function to the person writing it, so a call
        # they wrote against the HogQL signature must not fail in Hog. The VM checks maxArgs before
        # it dispatches, so a maxArgs below the HogQL limit turns such a call into a runtime error.
        too_strict = []
        for name, stl_fn in STL.items():
            hogql_fn = HOGQL_FUNCTIONS.get(name)
            if hogql_fn is None or stl_fn.maxArgs is None or name in NARROWER_THAN_HOGQL_ON_PURPOSE:
                continue
            if hogql_fn.max_args is None or hogql_fn.max_args > stl_fn.maxArgs:
                limit = "unbounded" if hogql_fn.max_args is None else hogql_fn.max_args
                too_strict.append(f"{name}: Hog maxArgs={stl_fn.maxArgs}, HogQL accepts {limit}")

        assert too_strict == []
