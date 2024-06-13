import json
from typing import Any, Optional
from collections.abc import Callable


from hogvm.python.execute import execute_bytecode, get_nested_value
from hogvm.python.operation import Operation as op, HOGQL_BYTECODE_IDENTIFIER as _H
from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr, parse_program


class TestBytecodeExecute:
    def _run(self, expr: str) -> Any:
        globals = {
            "properties": {"foo": "bar", "nullValue": None},
        }
        return execute_bytecode(create_bytecode(parse_expr(expr)), globals).result

    def _run_program(
        self, code: str, functions: Optional[dict[str, Callable[..., Any]]] = None, globals: Optional[dict] = None
    ) -> Any:
        if not globals:
            globals = {
                "properties": {"foo": "bar", "nullValue": None},
            }
        program = parse_program(code)
        bytecode = create_bytecode(program, supported_functions=set(functions.keys()) if functions else None)
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

        chain = ["properties", "list", 1]
        assert get_nested_value(my_dict, chain) == "item2"

        chain = ["properties", "tuple", 2]
        assert get_nested_value(my_dict, chain) == "item3"

    def test_errors(self):
        try:
            execute_bytecode([_H, op.TRUE, op.CALL, "notAFunction", 1], {})
        except Exception as e:
            assert str(e) == "Unsupported function call: notAFunction"
        else:
            raise AssertionError("Expected Exception not raised")

        try:
            execute_bytecode([_H, op.CALL, "notAFunction", 1], {})
        except Exception as e:
            assert str(e) == "Stack underflow"
        else:
            raise AssertionError("Expected Exception not raised")

        try:
            execute_bytecode([_H, op.TRUE, op.TRUE, op.NOT], {})
        except Exception as e:
            assert str(e) == "Invalid bytecode. More than one value left on stack"
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
        assert execute_bytecode([_H, op.INTEGER, 1, op.CALL, "stringify", 1, op.RETURN], {}, functions).result == "one"
        assert execute_bytecode([_H, op.INTEGER, 2, op.CALL, "stringify", 1, op.RETURN], {}, functions).result == "two"
        assert (
            execute_bytecode([_H, op.STRING, "2", op.CALL, "stringify", 1, op.RETURN], {}, functions).result == "zero"
        )

    def test_bytecode_variable_assignment(self):
        program = parse_program("let a := 1 + 2; return a;")
        bytecode = create_bytecode(program)
        assert bytecode == [
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
        ]

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
        bytecode = create_bytecode(program)
        assert bytecode == [
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
        bytecode = create_bytecode(program)
        assert bytecode == [
            _H,
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
        bytecode = create_bytecode(program)
        assert bytecode == [
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
                    print(i) -- loops 3 times
                    j := j + 2
                }
                return j
                """
            )
            == 6
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
        assert bytecode == [
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
        ]

        response = execute_bytecode(bytecode).result
        assert response == 7

        assert (
            self._run_program(
                """
                fn add(a, b) {
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
                fn add(a, b) {
                    return a + b;
                }
                fn divide(a, b) {
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
                fn add(a, b) {
                    let c := a + b;
                    return c;
                }
                fn divide(a, b) {
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
                fn fibonacci(number) {
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
                fn doIt(a) {
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
                fn doIt() {
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
        assert self._run_program("return {key: 'value'};") == {None: "value"}
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

        assert self._run_program("let a := [1, 2, 3]; return a[1];") == 2
        assert self._run_program("return [1, 2, 3][1];") == 2
        assert self._run_program("return [1, [2, [3, 4]], 5][1][1][1];") == 4
        assert self._run_program("return [1, [2, [3, 4]], 5][1][1][1] + 1;") == 5
        assert self._run_program("return [1, [2, [3, 4]], 5].1.1.1;") == 4

    def test_bytecode_tuples(self):
        # assert self._run_program("return (,);"), ()
        assert self._run_program("return (1, 2, 3);") == (1, 2, 3)
        assert self._run_program("return (1, '2', 3);") == (1, "2", 3)
        assert self._run_program("return (1, (2, 3), 4);") == (1, (2, 3), 4)
        assert self._run_program("return (1, (2, (3, 4)), 5);") == (1, (2, (3, 4)), 5)
        assert self._run_program("let a := (1, 2, 3); return a[1];") == 2
        assert self._run_program("return (1, (2, (3, 4)), 5)[1][1][1];") == 4
        assert self._run_program("return (1, (2, (3, 4)), 5).1.1.1;") == 4
        assert self._run_program("return (1, (2, (3, 4)), 5)[1][1][1] + 1;") == 5

    def test_bytecode_nested(self):
        assert self._run_program("let r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.2.d.1;") == 3
        assert self._run_program("let r := [1, 2, {'d': (1, 3, 42, 6)}]; return r[2].d[2];") == 42
        assert self._run_program("let r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.2['d'][3];") == 6
        assert self._run_program("let r := {'d': (1, 3, 42, 6)}; return r.d.1;") == 3

    def test_bytecode_nested_modify(self):
        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r.2.d.2 := 3;
                return r.2.d.2;
                """
            )
            == 3
        )

        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r[2].d[2] := 3;
                return r[2].d[2];
                """
            )
            == 3
        )

        assert self._run_program(
            """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r[2].c := [666];
                return r[2];
                """
        ) == {"d": [1, 3, 42, 3], "c": [666]}

        assert self._run_program(
            """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r[2].d[2] := 3;
                return r[2].d;
                """
        ) == [1, 3, 3, 3]

        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                r.2['d'] := ['a', 'b', 'c', 'd'];
                return r[2].d[2];
                """
            )
            == "c"
        )

        assert (
            self._run_program(
                """
                let r := [1, 2, {'d': [1, 3, 42, 3]}];
                let g := 'd';
                r.2[g] := ['a', 'b', 'c', 'd'];
                return r[2].d[2];
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
