# flake8: noqa: T201
import sys

from antlr4 import *
from antlr4.tree.Trees import Trees
from HogQLLexer import HogQLLexer
from HogQLParser import HogQLParser
from HogQLParserListener import HogQLParserListener
from HogQLPrinter import HogQLPrinter


def extract_original_text(self, ctx):
    token_source = ctx.start.getTokenSource()
    input_stream = token_source.inputStream
    start, stop = ctx.start.start, ctx.stop.stop
    return input_stream.getText(start, stop)


class KeyPrinter(HogQLParserListener):
    def exitSelectStmt(self, ctx):
        print("Oh, a select!")

    def exitColumnsExprAsterisk(self, ctx):
        print("Oh, a star: *")

    def exitColumnsExprSubquery(self, ctx):
        print("Oh, a subquery hiding as a column: " + Trees.toStringTree(ctx, None, ctx.parser))

    def exitColumnsExprColumn(self, ctx):
        print("Oh, a column: " + Trees.toStringTree(ctx, None, ctx.parser))

    def exitQuery(self, ctx):
        print("Oh, a query!")


def main(argv):
    if argv and len(argv) > 1:
        input_stream = FileStream(argv[1])
    else:
        default_query = "select *, toStartOfMonth(foo, foo2) as bar, (select bla), (case when 1 < 2 then 'string' else 'strang' end) from events"
        print(f"Input query: {default_query}")
        input_query = default_query
        input_stream = InputStream(input_query)

    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    tree = parser.query()
    response = HogQLPrinter().visit(tree)
    print(f"With changes: {response}")
    print(f"Parse tree: {Trees.toStringTree(tree, None, parser)}")


if __name__ == "__main__":
    main(sys.argv)
