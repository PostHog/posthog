import pickle
from itertools import product
from typing import Dict, Set

from django.core.management.base import BaseCommand

from posthog.clickhouse.client import sync_execute
from posthog.hogql.ast import IntegerType, StringType, FloatType, BooleanType, ArrayType, TupleType, LambdaType
from posthog.hogql.functions import HOGQL_CLICKHOUSE_FUNCTIONS


# ex: python manage.py create_ch_migration <name of migration>
class Command(BaseCommand):
    help = "Measure HogQL function types"

    def handle(self, *args, **options):
        arg_types_with_defaults = [
            (IntegerType, "1"),
            (StringType, "'hello'"),
            (FloatType, "3.14"),
            (BooleanType, "true"),
            (ArrayType, "['1', '2']"),
            (ArrayType, "[1, 2]"),
            (ArrayType, "[true, false]"),
            (TupleType, "('1', '2')"),
            (TupleType, "(1, 2)"),
            (TupleType, "(true, false)"),
            (LambdaType, "x -> x"),
            (LambdaType, "(x, y) -> y"),
        ]
        # Too heavy
        skip_functions = ["pointInEllipses"]

        def load_state():
            try:
                with open("state.pkl", "rb") as f:
                    return pickle.load(f)
            except (FileNotFoundError, EOFError):
                return {}, {}

        def save_state(successes: Dict[str, Set[str]], failures: Dict[str, Set[str]]):
            with open("state.pkl", "wb") as f:
                pickle.dump((successes, failures), f)

        # Try to load previous state
        successes, failures = load_state()

        def generate_function_sql_queries():
            count = 0
            all_queries = []

            for func_name, meta in HOGQL_CLICKHOUSE_FUNCTIONS.items():
                print(func_name)  # noqa T201
                if func_name in skip_functions:
                    print("- Skipping (in skip_functions list)")  # noqa T201
                    continue
                if HOGQL_CLICKHOUSE_FUNCTIONS[func_name].signatures is not None:
                    print("- Skipping (has signatures)")  # noqa T201
                    continue

                if func_name not in successes:
                    successes[func_name] = set()
                else:
                    successes[func_name] = set(
                        query.replace("False", "false").replace("True", "true") for query in successes[func_name]
                    )

                if func_name not in failures:
                    failures[func_name] = set()
                else:
                    failures[func_name] = set(
                        query.replace("False", "false").replace("True", "true") for query in successes[func_name]
                    )

                if func_name not in successes:
                    successes[func_name] = set()
                else:
                    successes[func_name] = set(
                        query.replace("False", "false").replace("True", "true") for query in successes[func_name]
                    )

                max_args_start = meta.min_args if meta.max_args is None else meta.max_args
                max_args_end = min(6, meta.min_args + 2 if meta.max_args is None else meta.max_args)
                for max_args in range(max_args_start, max_args_end + 1):
                    for num_args in range(meta.min_args, max_args + 1):
                        for combination in product(arg_types_with_defaults, repeat=num_args):
                            args = ", ".join([str(arg[1]) for arg in combination])
                            query = f"SELECT {func_name}({args})"
                            if (
                                query in successes[func_name] or query in failures[func_name]
                            ):  # Skip if we've seen this combination
                                continue
                            all_queries.append(query)
                            try:
                                # Replace this with your actual query execution function
                                sync_execute(query)
                                successes[func_name].add(query)
                            except Exception:
                                failures[func_name].add(query)
                            count += 1
                            if count % 1000 == 0:
                                save_state(successes, failures)  # Save the state after running the queries

                save_state(successes, failures)  # Save the state after running the queries
                for query in successes[func_name]:
                    print(f"- {query}")  # noqa T201
                if len(successes[func_name]) == 0:
                    print("- No successes")  # noqa T201

            return all_queries

        generate_function_sql_queries()
