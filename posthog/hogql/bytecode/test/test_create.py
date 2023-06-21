from posthog.hogql.bytecode.create import create_bytecode
from posthog.hogql.parser import parse_expr
from posthog.test.base import BaseTest


class TestBytecodeCreate(BaseTest):
    def test_bytecode_create(self):
        self.assertEqual(create_bytecode(parse_expr("1+2")), ["+", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 and 2")), ["and", 2, "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 or 2")), ["or", 2, "", 1, "", 2])
        self.assertEqual(
            create_bytecode(parse_expr("1 or (2 and 1) or 2")), ["or", 3, "", 1, "and", 2, "", 2, "", 1, "", 2]
        )
        self.assertEqual(
            create_bytecode(parse_expr("(1 or 2) and (1 or 2)")),
            ["and", 2, "or", 2, "", 1, "", 2, "or", 2, "", 1, "", 2],
        )
        self.assertEqual(create_bytecode(parse_expr("not true")), ["not", "", True])
        self.assertEqual(create_bytecode(parse_expr("properties.bla")), [".", 2, "properties", "bla"])
        self.assertEqual(
            create_bytecode(parse_expr("call('arg', 'another')")), ["()", "call", 2, "", "arg", "", "another"]
        )
        self.assertEqual(create_bytecode(parse_expr("1 = 2")), ["==", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 == 2")), ["==", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 < 2")), ["<", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 <= 2")), ["<=", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 > 2")), [">", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 >= 2")), [">=", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 like 2")), ["like", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 ilike 2")), ["ilike", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 not like 2")), ["not like", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 not ilike 2")), ["not ilike", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 in 2")), ["in", "", 1, "", 2])
        self.assertEqual(create_bytecode(parse_expr("1 not in 2")), ["not in", "", 1, "", 2])
        # self.assertEqual(create_bytecode(parse_expr("1 =~ 2")), ["=~", "", 1, "", 2])
        # self.assertEqual(create_bytecode(parse_expr("1 !~ 2")), ["!~", "", 1, "", 2])
