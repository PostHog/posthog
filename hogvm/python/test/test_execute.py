from typing import Any, Optional
from collections.abc import Callable


from hogvm.python.execute import execute_bytecode, get_nested_value
from hogvm.python.operation import Operation as op, HOGQL_BYTECODE_IDENTIFIER as _H
from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr, parse_program
from posthog.test.base import BaseTest


# @pytest.mark.skip(reason="These tests broke CI when ran with the typical backend tests")
class TestBytecodeExecute(BaseTest):
    def _run(self, expr: str) -> Any:
        fields = {
            "properties": {"foo": "bar", "nullValue": None},
        }
        return execute_bytecode(create_bytecode(parse_expr(expr)), fields).result

    def _run_program(self, code: str, functions: Optional[dict[str, Callable[..., Any]]] = None) -> Any:
        fields = {
            "properties": {"foo": "bar", "nullValue": None},
        }
        program = parse_program(code)
        bytecode = create_bytecode(program, supported_functions=set(functions.keys()) if functions else None)
        return execute_bytecode(bytecode, fields, functions).result

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
        self.assertEqual(self._run("ifNull(properties.foo, false)"), "bar")
        self.assertEqual(self._run("ifNull(properties.nullValue, false)"), False)
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
        chain: list[str] = ["properties", "bla"]
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

    def test_functions(self):
        def stringify(*args):
            if args[0] == 1:
                return "one"
            elif args[0] == 2:
                return "two"
            return "zero"

        functions = {"stringify": stringify}
        self.assertEqual(execute_bytecode([_H, op.INTEGER, 1, op.CALL, "stringify", 1], {}, functions).result, "one")
        self.assertEqual(execute_bytecode([_H, op.INTEGER, 2, op.CALL, "stringify", 1], {}, functions).result, "two")
        self.assertEqual(execute_bytecode([_H, op.STRING, "2", op.CALL, "stringify", 1], {}, functions).result, "zero")

    def test_bytecode_variable_assignment(self):
        program = parse_program("var a := 1 + 2; return a;")
        bytecode = create_bytecode(program)
        self.assertEqual(
            bytecode,
            [
                _H,
                op.INTEGER,
                2,
                op.INTEGER,
                1,
                op.PLUS,
                op.GET_LOCAL,
                0,
                op.RETURN,
                op.POP,
            ],
        )

        self.assertEqual(self._run_program("var a := 1 + 2; return a;"), 3)
        self.assertEqual(
            self._run_program(
                """
                var a := 1 + 2;
                var b := a + 4;
                return b;
                """
            ),
            7,
        )

    def test_bytecode_if_else(self):
        program = parse_program("if (true) return 1; else return 2;")
        bytecode = create_bytecode(program)
        self.assertEqual(
            bytecode,
            [
                _H,
                op.TRUE,
                op.JUMP_IF_FALSE,
                5,
                op.INTEGER,
                1,
                op.RETURN,
                op.JUMP,
                3,
                op.INTEGER,
                2,
                op.RETURN,
            ],
        )

        self.assertEqual(
            self._run_program("if (true) return 1; else return 2;"),
            1,
        )

        self.assertEqual(
            self._run_program("if (false) return 1; else return 2;"),
            2,
        )

        self.assertEqual(
            self._run_program("if (true) { return 1; } else { return 2; }"),
            1,
        )

        self.assertEqual(
            self._run_program(
                """
                var a := true;
                if (a) {
                    var a := 3;
                    return a + 2;
                } else {
                    return 2;
                }
                """
            ),
            5,
        )

    def test_bytecode_variable_reassignment(self):
        self.assertEqual(
            self._run_program(
                """
                var a := 1;
                a := a + 3;
                a := a * 2;
                return a;
                """
            ),
            8,
        )

    def test_bytecode_while(self):
        program = parse_program("while (true) 1 + 1;")
        bytecode = create_bytecode(program)
        self.assertEqual(
            bytecode,
            [_H, op.TRUE, op.JUMP_IF_FALSE, 8, op.INTEGER, 1, op.INTEGER, 1, op.PLUS, op.POP, op.JUMP, -11],
        )

        program = parse_program("while (toString('a')) { 1 + 1; } return 3;")
        bytecode = create_bytecode(program)
        self.assertEqual(
            bytecode,
            [
                _H,
                op.STRING,
                "a",
                op.CALL,
                "toString",
                1,
                op.JUMP_IF_FALSE,
                8,
                op.INTEGER,
                1,
                op.INTEGER,
                1,
                op.PLUS,
                op.POP,
                op.JUMP,
                -15,
                op.INTEGER,
                3,
                op.RETURN,
            ],
        )

        self.assertEqual(
            self._run_program(
                """
                var i := -1;
                while (false) {
                    1 + 1;
                }
                return i;
                """
            ),
            -1,
        )

        number_of_times = 0

        def call_three_times():
            nonlocal number_of_times
            number_of_times += 1
            return number_of_times <= 3

        self.assertEqual(
            self._run_program(
                """
                var i := 0;
                while (call_three_times()) {
                    true;
                }
                return i;
                """,
                {"call_three_times": call_three_times, "print": print},
            ),
            0,
        )

    def test_bytecode_while_var(self):
        self.assertEqual(
            self._run_program(
                """
                var i := 0;
                while (i < 3) {
                    i := i + 1;
                }
                return i;
                """
            ),
            3,
        )

    def test_bytecode_functions(self):
        program = parse_program(
            """
            fn add(a, b) {
                return a + b;
            }
            return add(3, 4);
            """
        )
        bytecode = create_bytecode(program)
        self.assertEqual(
            bytecode,
            [
                _H,
                op.DECLARE_FN,
                "add",
                2,
                6,
                op.GET_LOCAL,
                0,
                op.GET_LOCAL,
                1,
                op.PLUS,
                op.RETURN,
                op.INTEGER,
                4,
                op.INTEGER,
                3,
                op.CALL,
                "add",
                2,
                op.RETURN,
            ],
        )
        response = execute_bytecode(bytecode).result
        self.assertEqual(response, 7)

        self.assertEqual(
            self._run_program(
                """
                fn add(a, b) {
                    return a + b;
                }
                return add(3, 4) + 100 + add(1, 1);
                """
            ),
            109,
        )

        self.assertEqual(
            self._run_program(
                """
                fn add(a, b) {
                    return a + b;
                }
                fn divide(a, b) {
                    return a / b;
                }
                return divide(add(3, 4) + 100 + add(2, 1), 2);
                """
            ),
            55,
        )

        self.assertEqual(
            self._run_program(
                """
                fn add(a, b) {
                    var c := a + b;
                    return c;
                }
                fn divide(a, b) {
                    return a / b;
                }
                return divide(add(3, 4) + 100 + add(2, 1), 10);
                """
            ),
            11,
        )

    def test_bytecode_recursion(self):
        self.assertEqual(
            self._run_program(
                """
                fn fibonacci(number) {
                    if (number < 2) {
                        return number;
                    } else {
                        return fibonacci(number - 1) + fibonacci(number - 2);
                    }
                }
                return fibonacci(6);
                """
            ),
            8,
        )

    def test_bytecode_no_args(self):
        self.assertEqual(
            self._run_program(
                """
                fn doIt(a) {
                    var url := 'basdfasdf';
                    var second := 2 + 3;
                    return second;
                }
                var nr := doIt(1);
                return nr;
                """
            ),
            5,
        )
        self.assertEqual(
            self._run_program(
                """
                fn doIt() {
                    var url := 'basdfasdf';
                    var second := 2 + 3;
                    return second;
                }
                var nr := doIt();
                return nr;
                """
            ),
            5,
        )

    def test_bytecode_functions_stl(self):
        self.assertEqual(self._run_program("if (empty('') and notEmpty('234')) return length('123');"), 3)
        self.assertEqual(self._run_program("if (lower('Tdd4gh') == 'tdd4gh') return upper('test');"), "TEST")
        self.assertEqual(self._run_program("return reverse('spinner');"), "rennips")

    def test_bytecode_empty_statements(self):
        self.assertEqual(self._run_program(";"), None)
        self.assertEqual(self._run_program(";;"), None)
        self.assertEqual(self._run_program(";;return 1;;"), 1)
        self.assertEqual(self._run_program("return 1;;"), 1)
        self.assertEqual(self._run_program("return 1;"), 1)
        self.assertEqual(self._run_program("return 1;return 2;"), 1)
        self.assertEqual(self._run_program("return 1;return 2;;"), 1)
        self.assertEqual(self._run_program("return 1;return 2;return 3;"), 1)
        self.assertEqual(self._run_program("return 1;return 2;return 3;;"), 1)

    def test_bytecode_dicts(self):
        self.assertEqual(self._run_program("return {};"), {})
        self.assertEqual(self._run_program("return {'key': 'value'};"), {"key": "value"})
        self.assertEqual(
            self._run_program("return {'key': 'value', 'other': 'thing'};"), {"key": "value", "other": "thing"}
        )
        self.assertEqual(self._run_program("return {'key': {'otherKey': 'value'}};"), {"key": {"otherKey": "value"}})
        self.assertEqual(self._run_program("return {key: 'value'};"), {None: "value"})
        self.assertEqual(self._run_program("var key := 3; return {key: 'value'};"), {3: "value"})

        self.assertEqual(self._run_program("return {'key': 'value'}.key;"), "value")
        self.assertEqual(self._run_program("return {'key': 'value'}['key'];"), "value")
        self.assertEqual(self._run_program("return {'key': {'otherKey': 'value'}}.key.otherKey;"), "value")
        self.assertEqual(self._run_program("return {'key': {'otherKey': 'value'}}['key'].otherKey;"), "value")

    def test_bytecode_arrays(self):
        self.assertEqual(self._run_program("return [];"), [])
        self.assertEqual(self._run_program("return [1, 2, 3];"), [1, 2, 3])
        self.assertEqual(self._run_program("return [1, '2', 3];"), [1, "2", 3])
        self.assertEqual(self._run_program("return [1, [2, 3], 4];"), [1, [2, 3], 4])
        self.assertEqual(self._run_program("return [1, [2, [3, 4]], 5];"), [1, [2, [3, 4]], 5])

        self.assertEqual(self._run_program("var a := [1, 2, 3]; return a[1];"), 2)
        self.assertEqual(self._run_program("return [1, 2, 3][1];"), 2)
        self.assertEqual(self._run_program("return [1, [2, [3, 4]], 5][1][1][1];"), 4)
        self.assertEqual(self._run_program("return [1, [2, [3, 4]], 5][1][1][1] + 1;"), 5)
        self.assertEqual(self._run_program("return [1, [2, [3, 4]], 5].1.1.1;"), 4)

    def test_bytecode_tuples(self):
        # self.assertEqual(self._run_program("return (,);"), ())
        self.assertEqual(self._run_program("return (1, 2, 3);"), (1, 2, 3))
        self.assertEqual(self._run_program("return (1, '2', 3);"), (1, "2", 3))
        self.assertEqual(self._run_program("return (1, (2, 3), 4);"), (1, (2, 3), 4))
        self.assertEqual(self._run_program("return (1, (2, (3, 4)), 5);"), (1, (2, (3, 4)), 5))
        self.assertEqual(self._run_program("var a := (1, 2, 3); return a[1];"), 2)
        self.assertEqual(self._run_program("return (1, (2, (3, 4)), 5)[1][1][1];"), 4)
        self.assertEqual(self._run_program("return (1, (2, (3, 4)), 5).1.1.1;"), 4)
        self.assertEqual(self._run_program("return (1, (2, (3, 4)), 5)[1][1][1] + 1;"), 5)

    def test_bytecode_nested(self):
        self.assertEqual(self._run_program("var r := [1, 2, {'d': (1, 3, 42, 3)}]; return r.2.d.2;"), 42)
        self.assertEqual(self._run_program("var r := [1, 2, {'d': (1, 3, 42, 3)}]; return r[2].d[2];"), 42)
        self.assertEqual(self._run_program("var r := [1, 2, {'d': (1, 3, 42, 3)}]; return r.2['d'][2];"), 42)

    def test_bytecode_nested_modify(self):
        self.assertEqual(self._run_program("var r := [1, 2, {'d': (1, 3, 42, 3)}]; r.2.d.2 := 3; return r.2.d.2;"), 42)
        self.assertEqual(
            self._run_program("var r := [1, 2, {'d': (1, 3, 42, 3)}]; r[2].d[2] := 3; return r[2].d[2];"), 42
        )
        self.assertEqual(
            self._run_program(
                "var r := [1, 2, {'d': (1, 3, 42, 3)}]; r.2['d'] := ['a', 'b', 'c', 'd']; return r[2].d[2];"
            ),
            "c",
        )
