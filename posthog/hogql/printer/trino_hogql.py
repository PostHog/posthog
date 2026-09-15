from dataclasses import replace

from posthog.hogql.functions.core import HogQLFunctionMeta
from posthog.hogql.printer.hogql import HogQLPrinter


class TrinoHogQLPrinter(HogQLPrinter):
    # Trino's inferred column names need HogQL spelling with Trino's accepted signatures.
    def _find_aggregation(self, name: str) -> HogQLFunctionMeta | None:
        meta = super()._find_aggregation(name)
        if meta is None:
            return None
        if name == "medianExactWeighted":
            return replace(meta, min_args=2, max_args=2)
        if name == "medianExactWeightedIf":
            return replace(meta, min_args=3, max_args=3)
        if name in {"quantiles", "quantilesIf"}:
            count = 2 if name.endswith("If") else 1
            return replace(meta, min_args=count, max_args=count, min_params=1, max_params=None)
        return meta

    def _find_function(self, name: str) -> HogQLFunctionMeta | None:
        meta = super()._find_function(name)
        if meta is not None and name == "ifNotFinite":
            return replace(meta, min_args=2, max_args=2)
        return meta
