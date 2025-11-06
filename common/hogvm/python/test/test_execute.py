import json
from collections.abc import Callable
from typing import Any, Optional

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr, parse_program

from common.hogvm.python.execute import execute_bytecode, get_nested_value
from common.hogvm.python.operation import (
    HOGQL_BYTECODE_IDENTIFIER as _H,
    HOGQL_BYTECODE_VERSION as VERSION,
    Operation as op,
)
from common.hogvm.python.utils import UncaughtHogVMException


class TestBytecodeExecute:
    def _run(self, expr: str) -> Any:
        globals = {
            "properties": {"foo": "bar", "nullValue": None},
        }
        return execute_bytecode(create_bytecode(parse_expr(expr)).bytecode, globals).result

    def _run_program(
        self, code: str, functions: Optional[dict[str, Callable[..., Any]]] = None, globals: Optional[dict] = None
    ) -> Any:
        if not globals:
            globals = {
                "properties": {"foo": "bar", "nullValue": None},
            }
        program = parse_program(code)
        bytecode = create_bytecode(program, supported_functions=set(functions.keys()) if functions else None).bytecode
        response = execute_bytecode(bytecode, globals, functions)
        return response.result

    def test_bytecode_create(self):
        assert self._run("1 + 2") == 3
        assert self._run("1 - 2") == -1
        assert self._run("3 * 2") == 6
        assert self._run("3 / 2") == 1.5
        assert self._run("3 % 2") == 1
        assert self._run("1 and 2") is True
        assert self._run("1 or 0") is True
        assert self._run("1 and 0") is False
        assert self._run("1 or (0 and 1) or 2") is True
        assert self._run("(1 and 0) and 1") is False
        assert self._run("(1 or 2) and (1 or 2)") is True
        assert self._run("true") is True
        assert self._run("not true") is False
        assert self._run("false") is False
        assert self._run("null") is None
        assert self._run("3.14") == 3.14
        assert self._run("1 = 2") is False
        assert self._run("1 == 2") is False
        assert self._run("1 != 2") is True
        assert self._run("1 < 2") is True
        assert self._run("1 <= 2") is True
        assert self._run("1 > 2") is False
        assert self._run("1 >= 2") is False
        assert self._run("'a' like 'b'") is False
        assert self._run("'baa' like '%a%'") is True
        assert self._run("'baa' like '%x%'") is False
        assert self._run("'baa' ilike '%A%'") is True
        assert self._run("'baa' ilike '%C%'") is False
        assert self._run("'a' ilike 'b'") is False
        assert self._run("'a' not like 'b'") is True
        assert self._run("'a' not ilike 'b'") is True
        assert self._run("'a' in 'car'") is True
        assert self._run("'a' in 'foo'") is False
        assert self._run("'a' not in 'car'") is False
        assert self._run("properties.bla") is None
        assert self._run("properties.foo") == "bar"
        assert self._run("ifNull(properties.foo, false)") == "bar"
        assert self._run("ifNull(properties.nullValue, false)") is False
        assert self._run("concat('arg', 'another')") == "arganother"
        assert self._run("concat(1, NULL)") == "1"
        assert self._run("concat(true, false)") == "truefalse"
        assert self._run("match('test', 'e.*')") is True
        assert self._run("match('test', '^e.*')") is False
        assert self._run("match('test', 'x.*')") is False
        assert self._run("'test' =~ 'e.*'") is True
        assert self._run("'test' !~ 'e.*'") is False
        assert self._run("'test' =~ '^e.*'") is False
        assert self._run("'test' !~ '^e.*'") is True
        assert self._run("'test' =~ 'x.*'") is False
        assert self._run("'test' !~ 'x.*'") is True
        assert self._run("'test' ~* 'EST'") is True
        assert self._run("'test' =~* 'EST'") is True
        assert self._run("'test' !~* 'EST'") is False
        assert self._run("toString(1)") == "1"
        assert self._run("toString(1.5)") == "1.5"
        assert self._run("toString(true)") == "true"
        assert self._run("toString(null)") == "null"
        assert self._run("toString('string')") == "string"
        assert self._run("toInt('1')") == 1
        assert self._run("toInt('bla')") is None
        assert self._run("toFloat('1.2')") == 1.2
        assert self._run("toFloat('bla')") is None
        assert self._run("toUUID('asd')") == "asd"
        assert self._run("1 == null") is False
        assert self._run("1 != null") is True

    def test_nested_value(self):
        my_dict = {
            "properties": {
                "bla": "hello",
                "list": ["item1", "item2", "item3"],
                "tuple": ("item1", "item2", "item3"),
            }
        }
        chain: list[str] = ["properties", "bla"]
        assert get_nested_value(my_dict, chain) == "hello"

        chain = ["properties", "list", 2]
        assert get_nested_value(my_dict, chain) == "item2"

        chain = ["properties", "tuple", 3]
        assert get_nested_value(my_dict, chain) == "item3"

    def test_errors(self):
        try:
            execute_bytecode([_H, VERSION, op.TRUE, op.CALL_GLOBAL, "notAFunction", 1], {})
        except Exception as e:
            assert str(e) == "Unsupported function call: notAFunction"
        else:
            raise AssertionError("Expected Exception not raised")

        try:
            execute_bytecode([_H, VERSION, op.CALL_GLOBAL, "replaceOne", 1], {})
        except Exception as e:
            assert str(e) == "Stack underflow"
        else:
            raise AssertionError("Expected Exception not raised")

        try:
            execute_bytecode([_H, VERSION, op.TRUE, op.TRUE, op.NOT], {})
        except Exception as e:
            assert str(e) == "Invalid bytecode. More than one value left on stack"
        else:
            raise AssertionError("Expected Exception not raised")

    def test_memory_limits_1(self):
        # let string := 'banana'
        # for (let i := 0; i < 100; i := i + 1) {
        #   string := string || string
        # }
        bytecode = [
            "_h",
            32,
            "banana",
            33,
            0,
            33,
            100,
            36,
            1,
            15,
            40,
            18,
            36,
            0,
            36,
            0,
            2,
            "concat",
            2,
            37,
            0,
            33,
            1,
            36,
            1,
            6,
            37,
            1,
            39,
            -25,
            35,
            35,
        ]
        try:
            execute_bytecode(bytecode, {})
        except Exception as e:
            assert str(e) == "Memory limit of 67108864 bytes exceeded. Attempted to use 75497504 bytes"
        else:
            raise AssertionError("Expected Exception not raised")

    def test_memory_limits_2(self):
        bytecode = [
            "_h",
            32,
            "key",
            32,
            "value",
            32,
            "key2",
            32,
            "value2",
            42,
            2,
            32,
            "na",
            33,
            0,
            33,
            10000,
            36,
            2,
            15,
            40,
            52,
            33,
            16,
            36,
            2,
            15,
            40,
            9,
            36,
            1,
            36,
            1,
            2,
            "concat",
            2,
            37,
            1,
            36,
            0,
            36,
            2,
            32,
            "key_",
            2,
            "concat",
            2,
            32,
            "wasted",
            32,
            " batman!",
            36,
            1,
            32,
            "memory: ",
            2,
            "concat",
            3,
            32,
            "something",
            36,
            0,
            42,
            2,
            46,
            33,
            1,
            36,
            2,
            6,
            37,
            2,
            39,
            -59,
            35,
            35,
            35,
        ]
        try:
            execute_bytecode(bytecode, {})
        except Exception as e:
            assert str(e) == "Memory limit of 67108864 bytes exceeded. Attempted to use 67155164 bytes"
        else:
            raise AssertionError("Expected Exception not raised")

    def test_functions(self):
        def stringify(*args):
            if args[0] == 1:
                return "one"
            elif args[0] == 2:
                return "two"
            return "zero"

        functions = {"stringify": stringify}
        assert (
            execute_bytecode(
                [_H, VERSION, op.INTEGER, 1, op.CALL_GLOBAL, "stringify", 1, op.RETURN], {}, functions
            ).result
            == "one"
        )
        assert (
            execute_bytecode(
                [_H, VERSION, op.INTEGER, 2, op.CALL_GLOBAL, "stringify", 1, op.RETURN], {}, functions
            ).result
            == "two"
        )
        assert (
            execute_bytecode(
                [_H, VERSION, op.STRING, "2", op.CALL_GLOBAL, "stringify", 1, op.RETURN], {}, functions
            ).result
            == "zero"
        )

    def test_version_0_and_1(self):
        # version 0 of HogQL bytecode had arguments in a different order
        assert (
            execute_bytecode(["_h", op.STRING, "1", op.STRING, "2", op.CALL_GLOBAL, "concat", 2, op.RETURN]).result
            == "21"
        )
        assert (
            execute_bytecode(["_H", 1, op.STRING, "1", op.STRING, "2", op.CALL_GLOBAL, "concat", 2, op.RETURN]).result
            == "12"
        )

    def test_bytecode_variable_assignment(self):
        program = parse_program("let a := 1 + 2; return a;")
        bytecode = create_bytecode(program).bytecode
        assert bytecode == ["_H", 1, op.INTEGER, 2, op.INTEGER, 1, op.PLUS, op.GET_LOCAL, 0, op.RETURN, op.POP]

        assert self._run_program("let a := 1 + 2; return a;") == 3
        assert (
            self._run_program(
                """
                let a := 1 + 2;
                let b := a + 4;
                return b;
            """
            )
            == 7
        )

    def test_bytecode_if_else(self):
        program = parse_program("if (true) return 1; else return 2;")
        bytecode = create_bytecode(program).bytecode
        assert bytecode == [
            "_H",
            1,
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
        ]

        assert self._run_program("if (true) return 1; else return 2;") == 1

        assert self._run_program("if (false) return 1; else return 2;") == 2

        assert self._run_program("if (true) { return 1; } else { return 2; }") == 1

        assert (
            self._run_program(
                """
                let a := true;
                if (a) {
                    let a := 3;
                    return a + 2;
                } else {
                    return 2;
                }
            """
            )
            == 5
        )

    def test_bytecode_variable_reassignment(self):
        assert (
            self._run_program(
                """
                let a := 1;
                a := a + 3;
                a := a * 2;
                return a;
                """
            )
            == 8
        )

    def test_bytecode_while(self):
        program = parse_program("while (true) 1 + 1;")
        bytecode = create_bytecode(program).bytecode
        assert bytecode == [
            "_H",
            1,
            op.TRUE,
            op.JUMP_IF_FALSE,
            8,
            op.INTEGER,
            1,
            op.INTEGER,
            1,
            op.PLUS,
            op.POP,
            op.JUMP,
            -11,
        ]

        program = parse_program("while (toString('a')) { 1 + 1; } return 3;")
        bytecode = create_bytecode(program).bytecode
        assert bytecode == [
            "_H",
            1,
            op.STRING,
            "a",
            op.CALL_GLOBAL,
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
        ]

        assert (
            self._run_program(
                """
                let i := -1;
                while (false) {
                    1 + 1;
                }
                return i;
                """
            )
            == -1
        )

        number_of_times = 0

        def call_three_times():
            nonlocal number_of_times
            number_of_times += 1
            return number_of_times <= 3

        assert (
            self._run_program(
                """
                let i := 0;
                while (call_three_times()) {
                    true;
                }
                return i;
                """,
                {"call_three_times": call_three_times, "print": print},
            )
            == 0
        )

    def test_bytecode_while_var(self):
        assert (
            self._run_program(
                """
                let i := 0;
                while (i < 3) {
                    i := i + 1;
                }
                return i;
                """
            )
            == 3
        )

    def test_bytecode_for(self):
        assert (
            self._run_program(
                """
                let j := 0
                for (let i := 0; i < 3; i := i + 1) {
                    print(i) -- prints 3 times
                    j := j + 2
                }
                // print(i) -- global does not print
                return j
                """
            )
            == 6
        )

    def test_bytecode_functions(self):
        program = parse_program(
            """
            fun add(a, b) {
                return a + b;
            }
            return add(3, 4);
            """
        )
        bytecode = create_bytecode(program).bytecode
        assert bytecode == [
            "_H",
            VERSION,
            op.CALLABLE,
            "add",
            2,
            0,
            6,
            op.GET_LOCAL,
            1,
            op.GET_LOCAL,
            0,
            op.PLUS,
            op.RETURN,
            op.CLOSURE,
            0,
            op.INTEGER,
            3,
            op.INTEGER,
            4,
            op.GET_LOCAL,
            0,
            op.CALL_LOCAL,
            2,
            op.RETURN,
            op.POP,
        ]

        response = execute_bytecode(bytecode).result
        assert response == 7

        assert (
            self._run_program(
                """
                fun add(a, b) {
                    return a + b;
                }
                return add(3, 4) + 100 + add(1, 1);
                """
            )
            == 109
        )

        assert (
            self._run_program(
                """
                fun add(a, b) {
                    return a + b;
                }
                fun divide(a, b) {
                    return a / b;
                }
                return divide(add(3, 4) + 100 + add(2, 1), 2);
                """
            )
            == 55
        )

        assert (
            self._run_program(
                """
                fun add(a, b) {
                    let c := a + b;
                    return c;
                }
                fun divide(a, b) {
                    return a / b;
                }
                return divide(add(3, 4) + 100 + add(2, 1), 10);
                """
            )
            == 11
        )

    def test_bytecode_recursion(self):
        assert (
            self._run_program(
                """
                fun fibonacci(number) {
                    if (number < 2) {
                        return number;
                    } else {
                        return fibonacci(number - 1) + fibonacci(number - 2);
                    }
                }
                return fibonacci(6);
                """
            )
            == 8
        )

    def test_bytecode_no_args(self):
        assert (
            self._run_program(
                """
                fun doIt(a) {
                    let url := 'basdfasdf';
                    let second := 2 + 3;
                    return second;
                }
                let nr := doIt(1);
                return nr;
                """
            )
            == 5
        )

        assert (
            self._run_program(
                """
                fun doIt() {
                    let url := 'basdfasdf';
                    let second := 2 + 3;
                    return second;
                }
                let nr := doIt();
                return nr;
                """
            )
            == 5
        )

    def test_bytecode_functions_stl(self):
        assert self._run_program("if (empty('') and notEmpty('234')) return length('123');") == 3
        assert self._run_program("if (lower('Tdd4gh') == 'tdd4gh') return upper('test');") == "TEST"
        assert self._run_program("return reverse('spinner');") == "rennips"

    def test_bytecode_empty_statements(self):
        assert self._run_program(";") is None
        assert self._run_program(";;") is None
        assert self._run_program(";;return 1;;") == 1
        assert self._run_program("return 1;;") == 1
        assert self._run_program("return 1;") == 1
        assert self._run_program("return 1;return 2;") == 1
        assert self._run_program("return 1;return 2;;") == 1
        assert self._run_program("return 1;return 2;return 3;") == 1
        assert self._run_program("return 1;return 2;return 3;;") == 1

    def test_bytecode_dicts(self):
        assert self._run_program("return {};") == {}
        assert self._run_program("return {'key': 'value'};") == {"key": "value"}
        assert self._run_program("return {'key': 'value', 'other': 'thing'};") == {"key": "value", "other": "thing"}
        assert self._run_program("return {'key': {'otherKey': 'value'}};") == {"key": {"otherKey": "value"}}
        try:
            self._run_program("return {key: 'value'};")
        except Exception as e:
            assert str(e) == "Global variable not found: key"
        else:
            raise AssertionError("Expected Exception not raised")
        assert self._run_program("let key := 3; return {key: 'value'};") == {3: "value"}

        assert self._run_program("return {'key': 'value'}.key;") == "value"
        assert self._run_program("return {'key': 'value'}['key'];") == "value"
        assert self._run_program("return {'key': {'otherKey': 'value'}}.key.otherKey;") == "value"
        assert self._run_program("return {'key': {'otherKey': 'value'}}['key'].otherKey;") == "value"

    def test_bytecode_arrays(self):
        assert self._run_program("return [];") == []
        assert self._run_program("return [1, 2, 3];") == [1, 2, 3]
        assert self._run_program("return [1, '2', 3];") == [1, "2", 3]
        assert self._run_program("return [1, [2, 3], 4];") == [1, [2, 3], 4]
        assert self._run_program("return [1, [2, [3, 4]], 5];") == [1, [2, [3, 4]], 5]

        assert self._run_program("let a := [1, 2, 3]; return a[2];") == 2
        assert self._run_program("return [1, 2, 3][2];") == 2
        assert self._run_program("return [1, [2, [3, 4]], 5][2][2][2];") == 4
        assert self._run_program("return [1, [2, [3, 4]], 5][2][2][2] + 1;") == 5
        assert self._run_program("return [1, [2, [3, 4]], 5].2.2.2;") == 4

        try:
            self._run_program("return [1, 2, 3][0]")
        except Exception as e:
            assert str(e) == "Array access starts from 1"
        else:
            raise AssertionError("Expected Exception not raised")

    def test_bytecode_tuples(self):
        # assert self._run_program("return (,);"), ()
        assert self._run_program("return (1, 2, 3);") == (1, 2, 3)
        assert self._run_program("return (1, '2', 3);") == (1, "2", 3)
        assert self._run_program("return (1, (2, 3), 4);") == (1, (2, 3), 4)
        assert self._run_program("return (1, (2, (3, 4)), 5);") == (1, (2, (3, 4)), 5)
        assert self._run_program("let a := (1, 2, 3); return a[2];") == 2
        assert self._run_program("return (1, (2, (3, 4)), 5)[2][2][2];") == 4
        assert self._run_program("return (1, (2, (3, 4)), 5).2.2.2;") == 4
        assert self._run_program("return (1, (2, (3, 4)), 5)[2][2][2] + 1;") == 5

    def test_bytecode_nested(self):
        assert self._run_program("let r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.3.d.2;") == 3
        assert self._run_program("let r := [1, 2, {'d': (1, 3, 42, 6)}]; return r[3].d[3];") == 42
        assert self._run_program("let r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.3['d'][4];") == 6
        assert self._run_program("let r := {'d': (1, 3, 42, 6)}; return r.d.2;") == 3

    def test_bytecode_nested_modify(self):
        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r.3.d.3 := 3;
                return r.3.d.3;
                """
            )
            == 3
        )

        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r[3].d[3] := 3;
                return r[3].d[3];
                """
            )
            == 3
        )

        assert self._run_program(
            """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r[3].c := [666];
                return r[3];
                """
        ) == {"d": [1, 3, 42, 3], "c": [666]}

        assert self._run_program(
            """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r[3].d[3] := 3;
                return r[3].d;
                """
        ) == [1, 3, 3, 3]

        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r.3['d'] := ['a', 'b', 'c', 'd'];
                return r[3].d[3];
                """
            )
            == "c"
        )

        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                let g := 'd';
                r.3[g] := ['a', 'b', 'c', 'd'];
                return r[3].d[3];
                """
            )
            == "c"
        )

    def test_bytecode_nested_modify_dict(self):
        assert self._run_program(
            """
                let event := {
                    'event': '$pageview',
                    'properties': {
                        '$browser': 'Chrome',
                        '$os': 'Windows'
                    }
                };
                event['properties']['$browser'] := 'Firefox';
                return event;
                """
        ) == {"event": "$pageview", "properties": {"$browser": "Firefox", "$os": "Windows"}}
        assert self._run_program(
            """
                let event := {
                    'event': '$pageview',
                    'properties': {
                        '$browser': 'Chrome',
                        '$os': 'Windows'
                    }
                };
                event.properties.$browser := 'Firefox';
                return event;
                """
        ) == {"event": "$pageview", "properties": {"$browser": "Firefox", "$os": "Windows"}}
        assert self._run_program(
            """
                let event := {
                    'event': '$pageview',
                    'properties': {
                        '$browser': 'Chrome',
                        '$os': 'Windows'
                    }
                };
                let config := {};
                return event;
                """
        ) == {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}}

    def test_bytecode_parse_stringify_json(self):
        assert self._run_program("return jsonStringify({'$browser': 'Chrome', '$os': 'Windows' });") == json.dumps(
            {"$browser": "Chrome", "$os": "Windows"}
        )

        assert self._run_program(
            "return jsonStringify({'$browser': 'Chrome', '$os': 'Windows' }, 3);"  # pretty
        ) == json.dumps({"$browser": "Chrome", "$os": "Windows"}, indent=3)

        assert self._run_program("return jsonParse('[1,2,3]');") == [1, 2, 3]

        assert self._run_program(
            """
                let event := {
                    'event': '$pageview',
                    'properties': {
                        '$browser': 'Chrome',
                        '$os': 'Windows'
                    }
                };
                let json := jsonStringify(event);
                return jsonParse(json);
                """
        ) == {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}}

    def test_bytecode_modify_globals_after_copying(self):
        globals = {"globalEvent": {"event": "$pageview", "properties": {"$browser": "Chrome"}}}
        assert self._run_program(
            """
            let event := globalEvent;
            event.event := '$autocapture';
            event.properties.$browser := 'Firefox';
            return event;
        """,
            globals=globals,
        ) == {"event": "$autocapture", "properties": {"$browser": "Firefox"}}
        assert globals["globalEvent"]["event"] == "$pageview"
        assert globals["globalEvent"]["properties"]["$browser"] == "Chrome"

    def test_bytecode_if_multiif_ternary(self):
        values = []

        def noisy_print(str):
            nonlocal values
            values.append(str)
            return str

        self._run_program(
            """
            if (true) {
              noisy_print('true')
            } else {
              noisy_print('false')
            }
            """,
            {"noisy_print": noisy_print},
        )
        assert values == ["true"]

        values = []
        assert (
            self._run_program("return true ? noisy_print('true') : noisy_print('false')", {"noisy_print": noisy_print})
            == "true"
        )
        assert values == ["true"]

        values = []
        assert (
            self._run_program(
                "return true ? true ? noisy_print('true1') : noisy_print('true') : noisy_print('false')",
                {"noisy_print": noisy_print},
            )
            == "true1"
        )
        assert values == ["true1"]

        values = []
        assert (
            self._run_program(
                "return true ? false ? noisy_print('true1') : noisy_print('false1') : noisy_print('false2')",
                {"noisy_print": noisy_print},
            )
            == "false1"
        )
        assert values == ["false1"]

        values = []
        assert (
            self._run_program(
                "return false ? false ? noisy_print('true1') : noisy_print('false1') : noisy_print('false2')",
                {"noisy_print": noisy_print},
            )
            == "false2"
        )
        assert values == ["false2"]

        values = []
        assert (
            self._run_program("return false ? noisy_print('true') : noisy_print('false')", {"noisy_print": noisy_print})
            == "false"
        )
        assert values == ["false"]

        values = []
        assert (
            self._run_program(
                "return if(false, noisy_print('true'), noisy_print('false'))", {"noisy_print": noisy_print}
            )
            == "false"
        )
        assert values == ["false"]

        values = []
        assert (
            self._run_program(
                "return multiIf(false, noisy_print('true'), false, noisy_print('true'), noisy_print('false2'))",
                {"noisy_print": noisy_print},
            )
            == "false2"
        )
        assert values == ["false2"]

        values = []
        assert (
            self._run_program(
                "return multiIf(false, noisy_print('true'), true, noisy_print('true'), noisy_print('false2'))",
                {"noisy_print": noisy_print},
            )
            == "true"
        )
        assert values == ["true"]

        values = []
        assert (
            self._run_program(
                "return multiIf(true, noisy_print('true1'), false, noisy_print('true2'), noisy_print('false2'))",
                {"noisy_print": noisy_print},
            )
            == "true1"
        )
        assert values == ["true1"]

        values = []
        assert (
            self._run_program(
                "return multiIf(true, noisy_print('true1'), true, noisy_print('true2'), noisy_print('false2'))",
                {"noisy_print": noisy_print},
            )
            == "true1"
        )
        assert values == ["true1"]

    def test_bytecode_ifnull(self):
        values = []

        def noisy_print(str):
            nonlocal values
            values.append(str)
            return str

        assert (
            self._run_program(
                "return null ?? noisy_print('no'); noisy_print('post')",
                {"noisy_print": noisy_print},
            )
            == "no"
        )
        assert values == ["no"]

        values = []
        assert (
            self._run_program(
                "return noisy_print('yes') ?? noisy_print('no'); noisy_print('post')",
                {"noisy_print": noisy_print},
            )
            == "yes"
        )
        assert values == ["yes"]

    def test_bytecode_nullish(self):
        assert self._run_program("let a := {'b': {'d': 2}}; return (((a??{}).b)??{}).c") is None
        assert self._run_program("let a := {'b': {'d': 2}}; return (((a??{}).b)??{}).d") == 2
        assert self._run_program("let a := {'b': {'d': 2}}; return a?.b?.c") is None
        assert self._run_program("let a := {'b': {'d': 2}}; return a.b.c") is None
        assert self._run_program("let a := {'b': {'d': 2}}; return a?.b?.d") == 2
        assert self._run_program("let a := {'b': {'d': 2}}; return a.b.d") == 2
        assert self._run_program("let a := {'b': {'d': 2}}; return a?.b?.['c']") is None
        assert self._run_program("let a := {'b': {'d': 2}}; return a.b['c']") is None
        assert self._run_program("let a := {'b': {'d': 2}}; return a?.b?.['d']") == 2
        assert self._run_program("let a := {'b': {'d': 2}}; return a.b['d']") == 2
        assert self._run_program("return properties.foo") == "bar"
        assert self._run_program("return properties.not.here") is None

    def test_bytecode_uncaught_errors(self):
        try:
            self._run_program("throw Error('Not a good day')")
        except UncaughtHogVMException as e:
            assert str(e) == "Error('Not a good day')"
            assert e.type == "Error"
            assert e.message == "Not a good day"
            assert e.payload is None
        else:
            raise AssertionError("Expected Exception not raised")

        try:
            self._run_program("throw RetryError('Not a good day', {'key': 'value'})")
        except UncaughtHogVMException as e:
            assert str(e) == "RetryError('Not a good day')"
            assert e.type == "RetryError"
            assert e.message == "Not a good day"
            assert e.payload == {"key": "value"}
        else:
            raise AssertionError("Expected Exception not raised")

    def test_multiple_bytecodes(self):
        ret = lambda string: {"bytecode": ["_H", 1, op.STRING, string, op.RETURN]}
        call = lambda chunk: {"bytecode": ["_H", 1, op.STRING, chunk, op.CALL_GLOBAL, "import", 1, op.RETURN]}
        res = execute_bytecode(
            {
                "root": call("code2"),
                "code2": ret("banana"),
            }
        )
        assert res.result == "banana"

    def test_multiple_bytecodes_callback(self):
        ret = lambda string: {"bytecode": ["_H", 1, op.STRING, string, op.RETURN]}
        call = lambda chunk: {"bytecode": ["_H", 1, op.STRING, chunk, op.CALL_GLOBAL, "import", 1, op.RETURN]}
        res = execute_bytecode(
            {
                "root": call("code2"),
                "code2": call("code3"),
                "code3": call("code4"),
                "code4": call("code5"),
                "code5": ret("tomato"),
            }
        )
        assert res.result == "tomato"

    def test_in_cohort_operation(self):
        # Test IN_COHORT with cohort_ids from globals
        bytecode = [
            _H,
            VERSION,
            op.INTEGER,
            123,  # cohort ID to check
            op.STRING,
            "cohort_ids",  # Global variable name
            op.GET_GLOBAL,  # Get cohort_ids from globals
            1,  # Arg count for GET_GLOBAL
            op.IN_COHORT,  # Check membership
        ]

        # Person is in cohort 123
        result = execute_bytecode(bytecode, {"cohort_ids": [45, 123, 789]})
        assert result.result is True

        # Person is not in cohort 999
        bytecode = [
            _H,
            VERSION,
            op.INTEGER,
            999,  # cohort ID to check
            op.STRING,
            "cohort_ids",
            op.GET_GLOBAL,
            1,
            op.IN_COHORT,
        ]
        result = execute_bytecode(bytecode, {"cohort_ids": [45, 123, 789]})
        assert result.result is False

        # Test NOT_IN_COHORT
        bytecode = [
            _H,
            VERSION,
            op.INTEGER,
            999,  # cohort ID to check
            op.STRING,
            "cohort_ids",
            op.GET_GLOBAL,
            1,
            op.NOT_IN_COHORT,
        ]
        result = execute_bytecode(bytecode, {"cohort_ids": [45, 123, 789]})
        assert result.result is True

        # Test with empty cohort list
        bytecode = [
            _H,
            VERSION,
            op.INTEGER,
            123,
            op.STRING,
            "cohort_ids",
            op.GET_GLOBAL,
            1,
            op.IN_COHORT,
        ]
        result = execute_bytecode(bytecode, {"cohort_ids": []})
        assert result.result is False

        # Test with missing cohort_ids in globals - GET_GLOBAL will throw an exception
        # This is expected behavior as globals that don't exist raise an error
        bytecode = [
            _H,
            VERSION,
            op.INTEGER,
            123,
            op.STRING,
            "cohort_ids",
            op.GET_GLOBAL,
            1,
            op.IN_COHORT,
        ]
        try:
            result = execute_bytecode(bytecode, {})
            raise AssertionError("Should have raised an exception")
        except Exception as e:
            assert "Global variable not found: cohort_ids" in str(e)

        # Test with string cohort ID that should be converted to int
        bytecode = [
            _H,
            VERSION,
            op.STRING,
            "123",  # String cohort ID
            op.STRING,
            "cohort_ids",
            op.GET_GLOBAL,
            1,
            op.IN_COHORT,
        ]
        result = execute_bytecode(bytecode, {"cohort_ids": [45, 123, 789]})
        assert result.result is True
