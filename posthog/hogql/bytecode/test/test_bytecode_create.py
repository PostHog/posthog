from posthog.hogql.bytecode.create import to_bytecode
from posthog.hogql.bytecode.operation import Operation as op, HOGQL_BYTECODE_IDENTIFIER as _H
from posthog.hogql.errors import NotImplementedException
from posthog.test.base import BaseTest


class TestBytecodeCreate(BaseTest):
    def test_bytecode_create(self):
        self.assertEqual(to_bytecode("1 + 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.PLUS])
        self.assertEqual(to_bytecode("1 and 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.AND, 2])
        self.assertEqual(to_bytecode("1 or 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.OR, 2])
        self.assertEqual(
            to_bytecode("1 or (2 and 1) or 2"),
            [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.CONSTANT, 2, op.AND, 2, op.CONSTANT, 1, op.OR, 3],
        )
        self.assertEqual(
            to_bytecode("(1 or 2) and (1 or 2)"),
            [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.OR, 2, op.CONSTANT, 2, op.CONSTANT, 1, op.OR, 2, op.AND, 2],
        )
        self.assertEqual(to_bytecode("not true"), [_H, op.CONSTANT, True, op.NOT])
        self.assertEqual(
            to_bytecode("properties.bla"), [_H, op.CONSTANT, "bla", op.CONSTANT, "properties", op.FIELD, 2]
        )
        self.assertEqual(
            to_bytecode("call('arg', 'another')"), [_H, op.CONSTANT, "another", op.CONSTANT, "arg", op.CALL, "call", 2]
        )
        self.assertEqual(to_bytecode("1 = 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.EQ])
        self.assertEqual(to_bytecode("1 == 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.EQ])
        self.assertEqual(to_bytecode("1 != 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.NOT_EQ])
        self.assertEqual(to_bytecode("1 < 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.LT])
        self.assertEqual(to_bytecode("1 <= 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.LT_EQ])
        self.assertEqual(to_bytecode("1 > 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.GT])
        self.assertEqual(to_bytecode("1 >= 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.GT_EQ])
        self.assertEqual(to_bytecode("1 like 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.LIKE])
        self.assertEqual(to_bytecode("1 ilike 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.ILIKE])
        self.assertEqual(to_bytecode("1 not like 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.NOT_LIKE])
        self.assertEqual(to_bytecode("1 not ilike 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.NOT_ILIKE])
        self.assertEqual(to_bytecode("1 in 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.IN])
        self.assertEqual(to_bytecode("1 not in 2"), [_H, op.CONSTANT, 2, op.CONSTANT, 1, op.NOT_IN])
        self.assertEqual(to_bytecode("'string' ~ 'regex'"), [_H, op.CONSTANT, "regex", op.CONSTANT, "string", op.REGEX])
        self.assertEqual(
            to_bytecode("'string' =~ 'regex'"), [_H, op.CONSTANT, "regex", op.CONSTANT, "string", op.REGEX]
        )
        self.assertEqual(
            to_bytecode("'string' !~ 'regex'"), [_H, op.CONSTANT, "regex", op.CONSTANT, "string", op.NOT_REGEX]
        )
        self.assertEqual(
            to_bytecode("match('test', 'e.*')"), [_H, op.CONSTANT, "e.*", op.CONSTANT, "test", op.CALL, "match", 2]
        )
        self.assertEqual(
            to_bytecode("match('test', '^e.*')"), [_H, op.CONSTANT, "^e.*", op.CONSTANT, "test", op.CALL, "match", 2]
        )
        self.assertEqual(
            to_bytecode("match('test', 'x.*')"), [_H, op.CONSTANT, "x.*", op.CONSTANT, "test", op.CALL, "match", 2]
        )

    def test_bytecode_create_error(self):
        with self.assertRaises(NotImplementedException) as e:
            to_bytecode("(select 1)")
        self.assertEqual(str(e.exception), "Unsupported HogQL bytecode node: Visitor has no method visit_select_query")
