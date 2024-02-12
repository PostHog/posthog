from posthog.hogql.bytecode import to_bytecode
from hogvm.python.operation import Operation as op, HOGQL_BYTECODE_IDENTIFIER as _H
from posthog.hogql.errors import NotImplementedException
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
            [_H, op.STRING, "bla", op.STRING, "properties", op.FIELD, 2],
        )
        self.assertEqual(
            to_bytecode("concat('arg', 'another')"),
            [_H, op.STRING, "another", op.STRING, "arg", op.CALL, "concat", 2],
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
            [_H, op.STRING, "e.*", op.STRING, "test", op.CALL, "match", 2],
        )
        self.assertEqual(
            to_bytecode("match('test', '^e.*')"),
            [_H, op.STRING, "^e.*", op.STRING, "test", op.CALL, "match", 2],
        )
        self.assertEqual(
            to_bytecode("match('test', 'x.*')"),
            [_H, op.STRING, "x.*", op.STRING, "test", op.CALL, "match", 2],
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

    def test_bytecode_create_error(self):
        with self.assertRaises(NotImplementedException) as e:
            to_bytecode("(select 1)")
        self.assertEqual(str(e.exception), "Visitor has no method visit_select_query")

        with self.assertRaises(NotImplementedException) as e:
            to_bytecode("1 in cohort 2")
        self.assertEqual(str(e.exception), "Cohort operations are not supported")
