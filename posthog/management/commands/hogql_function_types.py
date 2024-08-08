import itertools
import pickle

from django.core.management.base import BaseCommand

from posthog.clickhouse.client import sync_execute
from posthog.hogql.ast import DateTimeType, DateType, IntegerType, StringType, FloatType, BooleanType, TupleType
from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS, AnyConstantType, HogQLFunctionMeta


class Command(BaseCommand):
    help = "Measure HogQL function types"

    def handle(self, *args, **options):
        arg_types_with_defaults = {
            IntegerType: "1",
            StringType: "'hello'",
            FloatType: "3.14",
            BooleanType: "true",
        }
        # Too heavy
        skip_functions = ["pointInEllipses"]

        def load_state():
            try:
                with open("state.pkl", "rb") as f:
                    return pickle.load(f)
            except (FileNotFoundError, EOFError):
                return {}, {}

        def save_state(blah: dict[str, HogQLFunctionMeta]):
            with open("state.pkl", "wb") as f:
                pickle.dump(blah, f)

        # Try to load previous state
        # successes, failures = load_state()

        def get_arg_value(arg_type: AnyConstantType) -> str:
            if arg_type.nullable:
                return "null"

            if isinstance(arg_type, IntegerType):
                return "1"
            if isinstance(arg_type, StringType):
                if arg_type.is_timezone_type:
                    return "UTC"
                return "'hello'"
            if isinstance(arg_type, FloatType):
                return "3.14"
            if isinstance(arg_type, BooleanType):
                return "true"
            if isinstance(arg_type, DateTimeType):
                return "now()"
            if isinstance(arg_type, DateType):
                return "toDate(now())"

            return ""

        newFuncs: dict[str, HogQLFunctionMeta] = {}

        for func_name, meta in HOGQL_CLICKHOUSE_FUNCTIONS.items():
            if not meta.signatures:
                continue

            newSig: list[tuple[tuple[AnyConstantType, ...], AnyConstantType]] = []

            for argsTuple, return_type in meta.signatures:
                table = list(itertools.product([True, False], repeat=len(argsTuple)))
                combo: list[list[AnyConstantType]] = []

                if any(isinstance(c, TupleType) for c in argsTuple):
                    print("Ignoring tuple args")
                    continue

                for argSet in table:
                    combo.append([argsTuple[index].__class__(nullable=z) for index, z in enumerate(argSet)])  # type: ignore

                for argSet2 in combo:
                    args = ", ".join(get_arg_value(blah) for blah in argSet2)
                    query = f"SELECT {func_name}({args})"
                    print(f"Querying... {query}")
                    try:
                        res = sync_execute(query)[0][0]
                        print("Success")
                        print(res)
                        # Clone return_type
                        if res is None:
                            return_type.nullable = True
                        else:
                            return_type.nullable = False
                        newSig.append((tuple(argSet2), return_type))
                    except Exception:
                        print("Exception")
                        continue
            meta.signatures = newSig
            newFuncs[func_name] = meta
        save_state(newFuncs)

        for func_name, meta in newFuncs.items():
            print("==========")
            print(func_name)
            print(meta)
            print("==========")

        # def generate_function_sql_queries():
        #     count = 0
        #     all_queries = []

        #     for func_name, meta in HOGQL_CLICKHOUSE_FUNCTIONS.items():
        #         print(func_name)  # noqa T201
        #         if func_name in skip_functions:
        #             print("- Skipping (in skip_functions list)")  # noqa T201
        #             continue
        #         if HOGQL_CLICKHOUSE_FUNCTIONS[func_name].signatures is not None:
        #             print("- Skipping (has signatures)")  # noqa T201
        #             continue

        #         if func_name not in successes:
        #             successes[func_name] = set()
        #         else:
        #             successes[func_name] = set(
        #                 query.replace("False", "false").replace("True", "true") for query in successes[func_name]
        #             )

        #         if func_name not in failures:
        #             failures[func_name] = set()
        #         else:
        #             failures[func_name] = set(
        #                 query.replace("False", "false").replace("True", "true") for query in successes[func_name]
        #             )

        #         if func_name not in successes:
        #             successes[func_name] = set()
        #         else:
        #             successes[func_name] = set(
        #                 query.replace("False", "false").replace("True", "true") for query in successes[func_name]
        #             )

        #         max_args_start = meta.min_args if meta.max_args is None else meta.max_args
        #         max_args_end = min(6, meta.min_args + 2 if meta.max_args is None else meta.max_args)
        #         for max_args in range(max_args_start, max_args_end + 1):
        #             for num_args in range(meta.min_args, max_args + 1):
        #                 for combination in product(arg_types_with_defaults, repeat=num_args):
        #                     args = ", ".join([str(arg[1]) for arg in combination])
        #                     query = f"SELECT {func_name}({args})"
        #                     if (
        #                         query in successes[func_name] or query in failures[func_name]
        #                     ):  # Skip if we've seen this combination
        #                         continue
        #                     all_queries.append(query)
        #                     try:
        #                         # Replace this with your actual query execution function
        #                         sync_execute(query)
        #                         successes[func_name].add(query)
        #                     except Exception:
        #                         failures[func_name].add(query)
        #                     count += 1
        #                     if count % 1000 == 0:
        #                         save_state(successes, failures)  # Save the state after running the queries

        #         save_state(successes, failures)  # Save the state after running the queries
        #         for query in successes[func_name]:
        #             print(f"- {query}")  # noqa T201
        #         if len(successes[func_name]) == 0:
        #             print("- No successes")  # noqa T201

        #     return all_queries

        # generate_function_sql_queries()
