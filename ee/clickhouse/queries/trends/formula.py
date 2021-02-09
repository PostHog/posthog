import math

from clickhouse_driver import Client as SyncClient

from ee.clickhouse.client import ch_client, format_sql, substitute_params, sync_execute
from ee.clickhouse.queries.trends import breakdown
from ee.clickhouse.queries.trends.util import parse_response
from posthog.models.filters.filter import Filter


class ClickhouseTrendsFormula:
    def _run_formula_query(self, filter: Filter, team_id: int):
        letters = [chr(65 + i) for i in range(0, len(filter.entities))]
        queries = []
        for i, entity in enumerate(filter.entities):
            sql, params, _ = self._get_sql_for_entity(filter, entity, team_id)  # type: ignore
            queries.append(substitute_params(sql, params))

        sql = """SELECT
            sub_A.date,
            arrayMap(({letters_select}) -> {formula}, {selects})
            {breakdown_value}
            FROM ({first_query}) as sub_A
            {queries}
        """.format(
            letters_select=", ".join(letters),
            formula=filter.formula,  # formula is properly escaped in the filter
            selects=", ".join(["sub_{}.data".format(letters[i]) for i in range(0, len(filter.entities))]),
            breakdown_value=", trim(BOTH '\"' FROM sub_A.breakdown_value)" if filter.breakdown else "",
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
                ["CROSS JOIN ({}) as sub_{}".format(query, letters[i + 1]) for i, query in enumerate(queries[1:])]
            ),
        )
        print(format_sql(sql, {"formula": filter.formula}))
        result = sync_execute(sql, {"formula": filter.formula})
        return [
            parse_response(
                item,
                filter,
                {
                    "label": item[2] if filter.breakdown else "Formula ({})".format(filter.formula),
                    "data": [number if not math.isnan(number) else 0.0 for number in item[1]],
                },
            )
            for item in result
        ]
