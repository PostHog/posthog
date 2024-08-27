import pytest

from posthog.hogql.bytecode import to_bytecode, execute_hog
from hogvm.python.operation import Operation as op, HOGQL_BYTECODE_IDENTIFIER as _H
from posthog.hogql.errors import NotImplementedError, QueryError
from posthog.test.base import BaseTest


class TestBytecode(BaseTest):
    def test_bytecode_create(self):
        self.assertEqual(to_bytecode("1 + 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.PLUS])
        self.assertEqual(to_bytecode("1 and 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.AND, 2])
        self.assertEqual(to_bytecode("1 or 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.OR, 2])
        self.assertEqual(
            to_bytecode("1 or (2 and 1) or 2"),
            [
                _H,
                op.INTEGER,
                2,
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.AND,
                2,
                op.INTEGER,
                1,
                op.OR,
                3,
            ],
        )
        self.assertEqual(
            to_bytecode("(1 or 2) and (1 or 2)"),
            [
                _H,
                op.INTEGER,
                2,
                op.INTEGER,
                1,
                op.OR,
                2,
                op.INTEGER,
                2,
                op.INTEGER,
                1,
                op.OR,
                2,
                op.AND,
                2,
            ],
        )
        self.assertEqual(to_bytecode("not true"), [_H, op.TRUE, op.NOT])
        self.assertEqual(to_bytecode("true"), [_H, op.TRUE])
        self.assertEqual(to_bytecode("false"), [_H, op.FALSE])
        self.assertEqual(to_bytecode("null"), [_H, op.NULL])
        self.assertEqual(to_bytecode("3.14"), [_H, op.FLOAT, 3.14])
        self.assertEqual(
            to_bytecode("properties.bla"),
            [_H, op.STRING, "bla", op.STRING, "properties", op.GET_GLOBAL, 2],
        )
        self.assertEqual(
            to_bytecode("concat('arg', 'another')"),
            [_H, op.STRING, "another", op.STRING, "arg", op.CALL_GLOBAL, "concat", 2],
        )
        self.assertEqual(
            to_bytecode("ifNull(properties.email, false)"),
            [
                _H,
                op.STRING,
                "email",
                op.STRING,
                "properties",
                op.GET_GLOBAL,
                2,
                op.JUMP_IF_STACK_NOT_NULL,
                2,
                op.POP,
                op.FALSE,
            ],
        )
        self.assertEqual(to_bytecode("1 = 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.EQ])
        self.assertEqual(to_bytecode("1 == 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.EQ])
        self.assertEqual(to_bytecode("1 != 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.NOT_EQ])
        self.assertEqual(to_bytecode("1 < 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.LT])
        self.assertEqual(to_bytecode("1 <= 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.LT_EQ])
        self.assertEqual(to_bytecode("1 > 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.GT])
        self.assertEqual(to_bytecode("1 >= 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.GT_EQ])
        self.assertEqual(to_bytecode("1 like 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.LIKE])
        self.assertEqual(to_bytecode("1 ilike 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.ILIKE])
        self.assertEqual(to_bytecode("1 not like 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.NOT_LIKE])
        self.assertEqual(
            to_bytecode("1 not ilike 2"),
            [_H, op.INTEGER, 2, op.INTEGER, 1, op.NOT_ILIKE],
        )
        self.assertEqual(to_bytecode("1 in 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.IN])
        self.assertEqual(to_bytecode("1 not in 2"), [_H, op.INTEGER, 2, op.INTEGER, 1, op.NOT_IN])
        self.assertEqual(
            to_bytecode("'string' ~ 'regex'"),
            [_H, op.STRING, "regex", op.STRING, "string", op.REGEX],
        )
        self.assertEqual(
            to_bytecode("'string' =~ 'regex'"),
            [_H, op.STRING, "regex", op.STRING, "string", op.REGEX],
        )
        self.assertEqual(
            to_bytecode("'string' !~ 'regex'"),
            [_H, op.STRING, "regex", op.STRING, "string", op.NOT_REGEX],
        )
        self.assertEqual(
            to_bytecode("'string' ~* 'regex'"),
            [_H, op.STRING, "regex", op.STRING, "string", op.IREGEX],
        )
        self.assertEqual(
            to_bytecode("'string' =~* 'regex'"),
            [_H, op.STRING, "regex", op.STRING, "string", op.IREGEX],
        )
        self.assertEqual(
            to_bytecode("'string' !~* 'regex'"),
            [_H, op.STRING, "regex", op.STRING, "string", op.NOT_IREGEX],
        )
        self.assertEqual(
            to_bytecode("match('test', 'e.*')"),
            [_H, op.STRING, "e.*", op.STRING, "test", op.CALL_GLOBAL, "match", 2],
        )
        self.assertEqual(
            to_bytecode("match('test', '^e.*')"),
            [_H, op.STRING, "^e.*", op.STRING, "test", op.CALL_GLOBAL, "match", 2],
        )
        self.assertEqual(
            to_bytecode("match('test', 'x.*')"),
            [_H, op.STRING, "x.*", op.STRING, "test", op.CALL_GLOBAL, "match", 2],
        )
        self.assertEqual(to_bytecode("not('test')"), [_H, op.STRING, "test", op.NOT])
        self.assertEqual(to_bytecode("not 'test'"), [_H, op.STRING, "test", op.NOT])
        self.assertEqual(
            to_bytecode("or('test', 'test2')"),
            [_H, op.STRING, "test2", op.STRING, "test", op.OR, 2],
        )
        self.assertEqual(
            to_bytecode("and('test', 'test2')"),
            [_H, op.STRING, "test2", op.STRING, "test", op.AND, 2],
        )

    @pytest.mark.skip(reason="C++ parsing is not working for these cases yet.")
    def test_bytecode_objects(self):
        self.assertEqual(
            to_bytecode("[1, 2, 3]"),
            [_H, op.INTEGER, 1, op.INTEGER, 2, op.INTEGER, 3, op.ARRAY, 3],
        )
        self.assertEqual(
            to_bytecode("[1, 2, 3][1]"),
            [_H, op.INTEGER, 1, op.INTEGER, 2, op.INTEGER, 3, op.ARRAY, 3, op.INTEGER, 1, op.GET_PROPERTY, 1],
        )
        self.assertEqual(
            to_bytecode("{'a': 'b'}"),
            [_H, op.STRING, "a", op.STRING, "b", op.DICT, 1],
        )
        self.assertEqual(
            to_bytecode("{'a': 'b', 'c': 'd'}"),
            [_H, op.STRING, "a", op.STRING, "b", op.STRING, "c", op.STRING, "d", op.DICT, 2],
        )
        self.assertEqual(
            to_bytecode("{'a': 'b', 'c': {'a': 'b'}}"),
            [
                _H,
                op.STRING,
                "a",
                op.STRING,
                "b",
                op.STRING,
                "c",
                op.STRING,
                "a",
                op.STRING,
                "b",
                op.DICT,
                1,
                op.DICT,
                2,
            ],
        )
        self.assertEqual(
            to_bytecode("['a', 'b']"),
            [_H, op.STRING, "a", op.STRING, "b", op.ARRAY, 2],
        )
        self.assertEqual(
            to_bytecode("('a', 'b')"),
            [_H, op.STRING, "a", op.STRING, "b", op.TUPLE, 2],
        )

    def test_bytecode_create_not_implemented_error(self):
        with self.assertRaises(NotImplementedError) as e:
            to_bytecode("(select 1)")
        self.assertEqual(str(e.exception), "BytecodeCompiler has no method visit_select_query")

    def test_bytecode_create_query_error(self):
        with self.assertRaises(QueryError) as e:
            to_bytecode("1 in cohort 2")
        self.assertEqual(str(e.exception), "Cohort operations are not supported")

        with self.assertRaises(QueryError) as e:
            execute_hog("globalVar := 1;")
        self.assertEqual(
            str(e.exception), 'Variable "globalVar" not declared in this scope. Can not assign to globals.'
        )

        with self.assertRaises(QueryError) as e:
            execute_hog("globalVar.properties.bla := 1;")
        self.assertEqual(
            str(e.exception), 'Variable "globalVar" not declared in this scope. Can not assign to globals.'
        )

    def test_bytecode_execute(self):
        # Test a simple operations. The Hog execution itself is tested under hogvm/python/
        self.assertEqual(execute_hog("1 + 2", team=self.team).result, 3)
        self.assertEqual(
            execute_hog(
                """
            fn fibonacci(number) {
                if (number < 2) {
                    return number;
                } else {
                    return fibonacci(number - 1) + fibonacci(number - 2);
                }
            }
            return fibonacci(6);
        """,
                team=self.team,
            ).result,
            8,
        )
