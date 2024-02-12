from dataclasses import asdict, dataclass
from typing import List

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import BaseTest


@dataclass
class TestRow:
    a: int
    b: int


def insert(table: str, rows: List):
    columns = asdict(rows[0]).keys()

    all_values, params = [], {}
    for i, row in enumerate(rows):
        values = ", ".join([f"%(p_{i}_{j})s" for j, _ in enumerate(columns)])
        all_values.append(f"({values})")

        for j, column in enumerate(columns):
            params[f"p_{i}_{j}"] = getattr(row, column)

    sync_execute(
        f"""
            INSERT INTO {table} ({', '.join(columns)})
            VALUES {', '.join(all_values)}
        """,
        params,
    )


CREATE_T_1 = "CREATE TABLE t_1 (a UInt16 NOT NULL, b UInt8 NOT NULL) ENGINE = Memory"
CREATE_T_2 = "CREATE TABLE t_2 (a Int16 NOT NULL, b Int64 NULL) ENGINE = Memory"
DROP_T_1 = "DROP TABLE t_1 SYNC"
DROP_T_2 = "DROP TABLE t_2 SYNC"


class TestUsing(BaseTest):
    def setUp(self):
        super().setUp()
        try:
            sync_execute(CREATE_T_1)
            sync_execute(CREATE_T_2)
        except:
            pass

    def tearDown(self):
        super().tearDown()
        sync_execute(DROP_T_1)
        sync_execute(DROP_T_2)

    def test_using(self):
        # INSERT INTO t_1 (a, b)
        # VALUES
        # (1, 1),
        # (2, 2);

        # INSERT INTO t_2 (a, b)
        # VALUES
        # (-1, 1),
        # (1, -1),
        # (1, 1);

        insert("t_1", [TestRow(a=1, b=1), TestRow(a=2, b=2)])
        insert("t_2", [TestRow(a=-1, b=1), TestRow(a=1, b=-1), TestRow(a=1, b=1)])

        # query = parse_select(
        #     "SELECT a, b, toTypeName(a), toTypeName(b) FROM t_1 FULL JOIN t_2 ON t_1.a = t_2.a AND t_1.b = t_2.b",
        #     backend="python",
        # )

        # query = parse_select(
        #     "SELECT a, b, toTypeName(a), toTypeName(b) FROM t_1 FULL JOIN t_2 USING (a, b)",
        #     backend="python",
        # )

        query = parse_select(
            "SELECT event, timestamp, pdi.distinct_id FROM events e LEFT JOIN person_distinct_ids pdi USING distinct_id",
            backend="python",
        )

        #         65:76
        # children: [
        #     0: TerminalNode - "USING" 65:69
        #     1: TerminalNode - "("
        #     2: ColumnExprListContext - children:
        #       0: ColumnExprIdentifier 'a'
        #       1: TerminalNode ','
        #       2: ColumnExprIdentifier 'a'
        #     3: TerminalNode - ")"
        # ]

        response = execute_hogql_query(
            query,
            team=self.team,
        )

        self.assertEqual(response, 1)

    def test_using_asterisk(self):
        pass

        # "SELECT * FROM COUNTRIES JOIN CITIES USING (COUNTRY)"
        # "SELECT COUNTRIES.* FROM COUNTRIES JOIN CITIES USING (COUNTRY)"
        # "SELECT * FROM COUNTRIES JOIN CITIES USING (COUNTRY, COUNTRY_ISO_CODE)"
