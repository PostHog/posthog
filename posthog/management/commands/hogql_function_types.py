from copy import deepcopy
import itertools
import pickle

from django.core.management.base import BaseCommand

from posthog.clickhouse.client import sync_execute
from posthog.hogql.ast import DateTimeType, DateType, IntegerType, StringType, FloatType, BooleanType, TupleType
from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS, AnyConstantType, HogQLFunctionMeta


class Command(BaseCommand):
    help = "Measure HogQL function types"

    def handle(self, *args, **options):
        def save_state(blah: dict[str, HogQLFunctionMeta]):
            with open("state.pkl", "wb") as f:
                pickle.dump(blah, f)

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

            valid_signatures: list[tuple[tuple[AnyConstantType, ...], AnyConstantType]] = []

            for argsTuple, return_type in meta.signatures:
                table = list(itertools.product([True, False], repeat=len(argsTuple)))
                signatures: list[list[AnyConstantType]] = []

                if any(isinstance(c, TupleType) for c in argsTuple):
                    print("Ignoring tuple args")  # noqa: T201
                    continue

                for argSet in table:
                    signatures.append(
                        [
                            argsTuple[index].__class__(nullable=z, is_timezone_type=argsTuple[index].is_timezone_type)  # type: ignore
                            for index, z in enumerate(argSet)
                        ]
                    )

                for signature in signatures:
                    arg_values = [get_arg_value(arg_type) for arg_type in signature]
                    arg_values_str = ", ".join(arg_values)
                    query = f"SELECT {meta.clickhouse_name or func_name}({arg_values_str})"
                    print(f"Querying... {query}")  # noqa: T201
                    try:
                        res = sync_execute(query)[0][0]
                        print("Success")  # noqa: T201
                        copied_return_type = deepcopy(return_type)
                        if res is None:
                            copied_return_type.nullable = True
                        else:
                            copied_return_type.nullable = False
                        valid_signatures.append((tuple(signature), copied_return_type))
                    except Exception:
                        print("Exception")  # noqa: T201
                        continue
            meta.signatures = valid_signatures
            newFuncs[func_name] = meta
        save_state(newFuncs)

        for func_name, meta in newFuncs.items():
            print(  # noqa: T201
                f'"{func_name}": {meta},'.replace(
                    "min_params=0, max_params=0, aggregate=False, overloads=None, tz_aware=False, case_sensitive=True, ",
                    "",
                )
                .replace(
                    "min_params=0, max_params=0, aggregate=False, overloads=None, ",
                    "",
                )
                .replace("start=None, end=None, ", "")
                .replace("case_sensitive=True, ", "")
                .replace(", is_timezone_type=False", "")
                .replace(", suffix_args=None", "")
            )
