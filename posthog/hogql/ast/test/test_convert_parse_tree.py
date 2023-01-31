from antlr4 import CommonTokenStream, InputStream
from antlr4.tree.Tree import ParseTree

from posthog.hogql.ast import ast
from posthog.hogql.ast.convert_parse_tree import convert_parse_tree
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.test.base import BaseTest


def string_to_parse_tree_expr(query: str) -> ParseTree:
    input_stream = InputStream(query)
    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    return parser.columnExpr()


class TestConvertParseTree(BaseTest):
    def test_convert_expr(self):
        parse_tree = string_to_parse_tree_expr("1 + 2")
        ast_tree = convert_parse_tree(parse_tree)
        self.assertEqual(
            ast_tree,
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Add
            ),
        )
