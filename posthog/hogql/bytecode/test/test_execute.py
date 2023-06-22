from typing import Any

from posthog.hogql.bytecode.create import create_bytecode
from posthog.hogql.bytecode.execute import execute_bytecode
from posthog.hogql.parser import parse_expr
from posthog.test.base import BaseTest


class TestBytecodeCreate(BaseTest):
    def _run(self, expr: str) -> Any:
        fields = {
            "properties": {"foo": "bar"},
        }
        return execute_bytecode(create_bytecode(parse_expr(expr)), fields)

    def test_bytecode_create(self):
        self.assertEqual(self._run("1+2"), 3)
        # self.assertEqual(self._run("1 and 2"), 1)
        # self.assertEqual(self._run("1 or 2"), 1)
        # self.assertEqual(
        #     self._run("1 or (2 and 1) or 2"), 1
        # )
        # self.assertEqual(
        #     self._run("(1 or 2) and (1 or 2)"),
        #     1,
        # )
        # self.assertEqual(self._run("not true"), False)
        # self.assertEqual(self._run("properties.bla"), [".", 2, "properties", "bla"])
        # self.assertEqual(
        #     self._run("call('arg', 'another')"), ["()", "call", 2, "", "arg", "", "another"]
        # )
        # self.assertEqual(self._run("1 = 2"), ["==", "", 1, "", 2])
        # self.assertEqual(self._run("1 == 2"), ["==", "", 1, "", 2])
        # self.assertEqual(self._run("1 < 2"), ["<", "", 1, "", 2])
        # self.assertEqual(self._run("1 <= 2"), ["<=", "", 1, "", 2])
        # self.assertEqual(self._run("1 > 2"), [">", "", 1, "", 2])
        # self.assertEqual(self._run("1 >= 2"), [">=", "", 1, "", 2])
        # self.assertEqual(self._run("1 like 2"), ["like", "", 1, "", 2])
        # self.assertEqual(self._run("1 ilike 2"), ["ilike", "", 1, "", 2])
        # self.assertEqual(self._run("1 not like 2"), ["not like", "", 1, "", 2])
        # self.assertEqual(self._run("1 not ilike 2"), ["not ilike", "", 1, "", 2])
        # self.assertEqual(self._run("1 in 2"), ["in", "", 1, "", 2])
        # self.assertEqual(self._run("1 not in 2"), ["not in", "", 1, "", 2])
