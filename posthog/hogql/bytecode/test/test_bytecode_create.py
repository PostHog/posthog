from posthog.hogql.bytecode.create import to_bytecode
from posthog.hogql.errors import NotImplementedException
from posthog.test.base import BaseTest


class TestBytecodeCreate(BaseTest):
    def test_bytecode_create(self):
        self.assertEqual(to_bytecode("1 + 2"), ["_h", "", 2, "", 1, "+"])
        self.assertEqual(to_bytecode("1 and 2"), ["_h", "", 2, "", 1, "and", 2])
        self.assertEqual(to_bytecode("1 or 2"), ["_h", "", 2, "", 1, "or", 2])
        self.assertEqual(to_bytecode("1 or (2 and 1) or 2"), ["_h", "", 2, "", 1, "", 2, "and", 2, "", 1, "or", 3])
        self.assertEqual(
            to_bytecode("(1 or 2) and (1 or 2)"),
            ["_h", "", 2, "", 1, "or", 2, "", 2, "", 1, "or", 2, "and", 2],
        )
        self.assertEqual(to_bytecode("not true"), ["_h", "", True, "not"])
        self.assertEqual(to_bytecode("properties.bla"), ["_h", "", "bla", "", "properties", ".", 2])
        self.assertEqual(to_bytecode("call('arg', 'another')"), ["_h", "", "another", "", "arg", "()", "call", 2])
        self.assertEqual(to_bytecode("1 = 2"), ["_h", "", 2, "", 1, "=="])
        self.assertEqual(to_bytecode("1 == 2"), ["_h", "", 2, "", 1, "=="])
        self.assertEqual(to_bytecode("1 != 2"), ["_h", "", 2, "", 1, "!="])
        self.assertEqual(to_bytecode("1 < 2"), ["_h", "", 2, "", 1, "<"])
        self.assertEqual(to_bytecode("1 <= 2"), ["_h", "", 2, "", 1, "<="])
        self.assertEqual(to_bytecode("1 > 2"), ["_h", "", 2, "", 1, ">"])
        self.assertEqual(to_bytecode("1 >= 2"), ["_h", "", 2, "", 1, ">="])
        self.assertEqual(to_bytecode("1 like 2"), ["_h", "", 2, "", 1, "like"])
        self.assertEqual(to_bytecode("1 ilike 2"), ["_h", "", 2, "", 1, "ilike"])
        self.assertEqual(to_bytecode("1 not like 2"), ["_h", "", 2, "", 1, "not like"])
        self.assertEqual(to_bytecode("1 not ilike 2"), ["_h", "", 2, "", 1, "not ilike"])
        self.assertEqual(to_bytecode("1 in 2"), ["_h", "", 2, "", 1, "in"])
        self.assertEqual(to_bytecode("1 not in 2"), ["_h", "", 2, "", 1, "not in"])
        self.assertEqual(to_bytecode("match('test', 'e.*')"), ["_h", "", "e.*", "", "test", "()", "match", 2])
        self.assertEqual(to_bytecode("match('test', '^e.*')"), ["_h", "", "^e.*", "", "test", "()", "match", 2])
        self.assertEqual(to_bytecode("match('test', 'x.*')"), ["_h", "", "x.*", "", "test", "()", "match", 2])

    def test_bytecode_create_error(self):
        with self.assertRaises(NotImplementedException) as e:
            to_bytecode("(select 1)")
        self.assertEqual(str(e.exception), "Unsupported HogQL bytecode node: Visitor has no method visit_select_query")
