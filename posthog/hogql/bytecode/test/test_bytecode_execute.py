from typing import Any

from posthog.hogql.bytecode.create import create_bytecode
from posthog.hogql.bytecode.execute import execute_bytecode, get_nested_value
from posthog.hogql.parser import parse_expr
from posthog.test.base import BaseTest


class TestBytecodeExecute(BaseTest):
    def _run(self, expr: str) -> Any:
        fields = {
            "properties": {"foo": "bar"},
        }
        return execute_bytecode(create_bytecode(parse_expr(expr)), fields)

    def test_bytecode_create(self):
        self.assertEqual(self._run("1 + 2"), 3)
        self.assertEqual(self._run("1 - 2"), -1)
        self.assertEqual(self._run("3 * 2"), 6)
        self.assertEqual(self._run("3 / 2"), 1.5)
        self.assertEqual(self._run("3 % 2"), 1)
        self.assertEqual(self._run("1 and 2"), True)
        self.assertEqual(self._run("1 or 0"), True)
        self.assertEqual(self._run("1 and 0"), False)
        self.assertEqual(self._run("1 or (0 and 1) or 2"), True)
        self.assertEqual(self._run("(1 and 0) and 1"), False)
        self.assertEqual(self._run("(1 or 2) and (1 or 2)"), True)
        self.assertEqual(self._run("not true"), False)
        self.assertEqual(self._run("1 = 2"), False)
        self.assertEqual(self._run("1 == 2"), False)
        self.assertEqual(self._run("1 != 2"), True)
        self.assertEqual(self._run("1 < 2"), True)
        self.assertEqual(self._run("1 <= 2"), True)
        self.assertEqual(self._run("1 > 2"), False)
        self.assertEqual(self._run("1 >= 2"), False)
        self.assertEqual(self._run("'a' like 'b'"), False)
        self.assertEqual(self._run("'baa' like '%a%'"), True)
        self.assertEqual(self._run("'baa' like '%x%'"), False)
        self.assertEqual(self._run("'baa' ilike '%A%'"), True)
        self.assertEqual(self._run("'baa' ilike '%C%'"), False)
        self.assertEqual(self._run("'a' ilike 'b'"), False)
        self.assertEqual(self._run("'a' not like 'b'"), True)
        self.assertEqual(self._run("'a' not ilike 'b'"), True)
        self.assertEqual(self._run("'a' in 'car'"), True)
        self.assertEqual(self._run("'a' in 'foo'"), False)
        self.assertEqual(self._run("'a' not in 'car'"), False)
        self.assertEqual(self._run("properties.bla"), None)
        self.assertEqual(self._run("properties.foo"), "bar")
        self.assertEqual(self._run("concat('arg', 'another')"), "arganother")
        self.assertEqual(self._run("concat(1, NULL)"), "1")
        self.assertEqual(self._run("concat(true, false)"), "truefalse")
        self.assertEqual(self._run("match('test', 'e.*')"), True)
        self.assertEqual(self._run("match('test', '^e.*')"), False)
        self.assertEqual(self._run("match('test', 'x.*')"), False)

    def test_nested_value(self):
        my_dict = {
            "properties": {"bla": "hello", "list": ["item1", "item2", "item3"], "tuple": ("item1", "item2", "item3")}
        }
        chain = ["properties", "bla"]
        self.assertEqual(get_nested_value(my_dict, chain), "hello")

        chain = ["properties", "list", 1]
        self.assertEqual(get_nested_value(my_dict, chain), "item2")

        chain = ["properties", "tuple", 2]
        self.assertEqual(get_nested_value(my_dict, chain), "item3")
