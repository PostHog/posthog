import math
from itertools import accumulate
from typing import Any, Dict, List

from ee.clickhouse.queries.breakdown_props import get_breakdown_cohort_name
from ee.clickhouse.queries.trends.util import parse_response
from ee.clickhouse.sql.clickhouse import trim_quotes_expr
from posthog.client import sync_execute
from posthog.constants import NON_TIME_SERIES_DISPLAY_TYPES, TRENDS_CUMULATIVE
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


class ClickhouseTrendsFormula:
    def _run_formula_query(self, filter: Filter, team: Team):
        letters = [chr(65 + i) for i in range(0, len(filter.entities))]
        queries = []
        params: Dict[str, Any] = {}
        for idx, entity in enumerate(filter.entities):
            sql, entity_params, _ = self._get_sql_for_entity(filter, entity, team)  # type: ignore
            sql = sql.replace("%(", f"%({idx}_")
            entity_params = {f"{idx}_{key}": value for key, value in entity_params.items()}
            queries.append(sql)
            params = {**params, **entity_params}

        breakdown_value = (
            ", sub_A.breakdown_value"
            if filter.breakdown_type == "cohort"
            else f", {trim_quotes_expr('sub_A.breakdown_value')}"
        )
        is_aggregate = filter.display in NON_TIME_SERIES_DISPLAY_TYPES

        sql = """SELECT
            {date_select}
            arrayMap(({letters_select}) -> {formula}, {selects})
            {breakdown_value}
            {max_length}
            FROM ({first_query}) as sub_A
            {queries}
        """.format(
            date_select="'' as date," if is_aggregate else "sub_A.date,",
            letters_select=", ".join(letters),
            formula=filter.formula,  # formula is properly escaped in the filter
            # Need to wrap aggregates in arrays so we can still use arrayMap
            selects=", ".join(
                [
                    (f"[sub_{letter}.data]" if is_aggregate else f"arrayResize(sub_{letter}.data, max_length, 0)")
                    for letter in letters
                ]
            ),
            breakdown_value=breakdown_value if filter.breakdown else "",
            max_length=""
            if is_aggregate
            else ", arrayMax([{}]) as max_length".format(", ".join(f"length(sub_{letter}.data)" for letter in letters)),
            first_query=queries[0],
            queries="".join(
                [
                    "FULL OUTER JOIN ({query}) as sub_{letter} ON sub_A.breakdown_value = sub_{letter}.breakdown_value ".format(
                        query=query, letter=letters[i + 1]
                    )
                    for i, query in enumerate(queries[1:])
                ]
            )
            if filter.breakdown
            else "".join(
                [" CROSS JOIN ({}) as sub_{}".format(query, letters[i + 1]) for i, query in enumerate(queries[1:])]
            ),
        )
        result = sync_execute(sql, params)
        response = []
        for item in result:
            additional_values: Dict[str, Any] = {
                "label": self._label(filter, item),
            }
            if is_aggregate:
                additional_values["data"] = []
                additional_values["aggregated_value"] = item[1][0]
            else:
                additional_values["data"] = [
                    round(number, 2) if not math.isnan(number) and not math.isinf(number) else 0.0 for number in item[1]
                ]
                if filter.display == TRENDS_CUMULATIVE:
                    additional_values["data"] = list(accumulate(additional_values["data"]))
            additional_values["count"] = float(sum(additional_values["data"]))
            response.append(parse_response(item, filter, additional_values=additional_values))
        return response

    def _label(self, filter: Filter, item: List) -> str:
        if filter.breakdown:
            if filter.breakdown_type == "cohort":
                return get_breakdown_cohort_name(item[2])
            return item[2]
        return "Formula ({})".format(filter.formula)
