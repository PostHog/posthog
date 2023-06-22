from typing import List

from posthog.hogql.bytecode.create import create_bytecode
from posthog.hogql.errors import NotImplementedException
from posthog.hogql.parser import parse_expr
from posthog.test.base import BaseTest


class TestBytecodeCreate(BaseTest):
    def _run(self, expr: str) -> List[str]:
        return create_bytecode(parse_expr(expr))

    def test_bytecode_create(self):
        self.assertEqual(self._run("1+2"), ["_h", "", 2, "", 1, "+"])
        self.assertEqual(self._run("1 and 2"), ["_h", "", 2, "", 1, "and", 2])
        self.assertEqual(self._run("1 or 2"), ["_h", "", 2, "", 1, "or", 2])
        self.assertEqual(self._run("1 or (2 and 1) or 2"), ["_h", "", 2, "", 1, "", 2, "and", 2, "", 1, "or", 3])
        self.assertEqual(
            self._run("(1 or 2) and (1 or 2)"),
            ["_h", "", 2, "", 1, "or", 2, "", 2, "", 1, "or", 2, "and", 2],
        )
        self.assertEqual(self._run("not true"), ["_h", "", True, "not"])
        self.assertEqual(self._run("properties.bla"), ["_h", "", "bla", "", "properties", ".", 2])
        self.assertEqual(self._run("call('arg', 'another')"), ["_h", "", "another", "", "arg", "()", "call", 2])
        self.assertEqual(self._run("1 = 2"), ["_h", "", 2, "", 1, "=="])
        self.assertEqual(self._run("1 == 2"), ["_h", "", 2, "", 1, "=="])
        self.assertEqual(self._run("1 != 2"), ["_h", "", 2, "", 1, "!="])
        self.assertEqual(self._run("1 < 2"), ["_h", "", 2, "", 1, "<"])
        self.assertEqual(self._run("1 <= 2"), ["_h", "", 2, "", 1, "<="])
        self.assertEqual(self._run("1 > 2"), ["_h", "", 2, "", 1, ">"])
        self.assertEqual(self._run("1 >= 2"), ["_h", "", 2, "", 1, ">="])
        self.assertEqual(self._run("1 like 2"), ["_h", "", 2, "", 1, "like"])
        self.assertEqual(self._run("1 ilike 2"), ["_h", "", 2, "", 1, "ilike"])
        self.assertEqual(self._run("1 not like 2"), ["_h", "", 2, "", 1, "not like"])
        self.assertEqual(self._run("1 not ilike 2"), ["_h", "", 2, "", 1, "not ilike"])
        self.assertEqual(self._run("1 in 2"), ["_h", "", 2, "", 1, "in"])
        self.assertEqual(self._run("1 not in 2"), ["_h", "", 2, "", 1, "not in"])

    def test_bytecode_create_error(self):
        with self.assertRaises(NotImplementedException) as e:
            self._run("(select 1)")
        self.assertEqual(str(e.exception), "Unsupported HogQL bytecode node: Visitor has no method visit_select_query")
