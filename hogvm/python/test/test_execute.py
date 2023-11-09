from typing import Any

from hogvm.python.execute import execute_bytecode, get_nested_value
from hogvm.python.operation import Operation as op, HOGQL_BYTECODE_IDENTIFIER as _H
from posthog.hogql.bytecode import create_bytecode
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
        self.assertEqual(self._run("true"), True)
        self.assertEqual(self._run("not true"), False)
        self.assertEqual(self._run("false"), False)
        self.assertEqual(self._run("null"), None)
        self.assertEqual(self._run("3.14"), 3.14)
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
        self.assertEqual(self._run("'test' =~ 'e.*'"), True)
        self.assertEqual(self._run("'test' !~ 'e.*'"), False)
        self.assertEqual(self._run("'test' =~ '^e.*'"), False)
        self.assertEqual(self._run("'test' !~ '^e.*'"), True)
        self.assertEqual(self._run("'test' =~ 'x.*'"), False)
        self.assertEqual(self._run("'test' !~ 'x.*'"), True)
        self.assertEqual(self._run("'test' ~* 'EST'"), True)
        self.assertEqual(self._run("'test' =~* 'EST'"), True)
        self.assertEqual(self._run("'test' !~* 'EST'"), False)
        self.assertEqual(self._run("toString(1)"), "1")
        self.assertEqual(self._run("toString(1.5)"), "1.5")
        self.assertEqual(self._run("toString(true)"), "true")
        self.assertEqual(self._run("toString(null)"), "null")
        self.assertEqual(self._run("toString('string')"), "string")
        self.assertEqual(self._run("toInt('1')"), 1)
        self.assertEqual(self._run("toInt('bla')"), None)
        self.assertEqual(self._run("toFloat('1.2')"), 1.2)
        self.assertEqual(self._run("toFloat('bla')"), None)
        self.assertEqual(self._run("toUUID('asd')"), "asd")
        self.assertEqual(self._run("1 == null"), False)
        self.assertEqual(self._run("1 != null"), True)

    def test_nested_value(self):
        my_dict = {
            "properties": {
                "bla": "hello",
                "list": ["item1", "item2", "item3"],
                "tuple": ("item1", "item2", "item3"),
            }
        }
        chain = ["properties", "bla"]
        self.assertEqual(get_nested_value(my_dict, chain), "hello")

        chain = ["properties", "list", 1]
        self.assertEqual(get_nested_value(my_dict, chain), "item2")

        chain = ["properties", "tuple", 2]
        self.assertEqual(get_nested_value(my_dict, chain), "item3")

    def test_errors(self):
        with self.assertRaises(Exception) as e:
            execute_bytecode([_H, op.TRUE, op.CALL, "notAFunction", 1], {})
        self.assertEqual(str(e.exception), "Unsupported function call: notAFunction")

        with self.assertRaises(Exception) as e:
            execute_bytecode([_H, op.CALL, "notAFunction", 1], {})
        self.assertEqual(str(e.exception), "Unexpected end of bytecode")

        with self.assertRaises(Exception) as e:
            execute_bytecode([_H, op.TRUE, op.TRUE, op.NOT], {})
        self.assertEqual(str(e.exception), "Invalid bytecode. More than one value left on stack")
