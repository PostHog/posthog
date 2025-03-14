# Print compatibility table
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print a Hog/HogQL STL compatibility table"

    def handle(self, *args, **options):
        from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_COMPARISON_MAPPING

        hogql_functions = set(HOGQL_COMPARISON_MAPPING.keys()).union(set(HOGQL_CLICKHOUSE_FUNCTIONS.keys()))

        from common.hogvm.python.stl import STL
        from common.hogvm.python.stl.bytecode import BYTECODE_STL

        hog_functions = set(STL.keys()).union(set(BYTECODE_STL.keys()))

        hogql_functions = {
            fn
            if fn not in {f.lower() for f in hog_functions}
            else next((f for f in hog_functions if f.lower() == fn), fn)
            for fn in hogql_functions
        }

        all_functions = sorted(hog_functions.union(hogql_functions))
        max_length = max(len(fn) for fn in all_functions)

        for fn in all_functions:
            print(  # noqa: T201
                fn.ljust(max_length),
                "HogQL" if fn in hogql_functions else "     ",
                "Hog" if fn in hog_functions else "   ",
            )
