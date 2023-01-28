# flake8: noqa: T201
import sys

from antlr4 import *
from antlr4.tree.Trees import Trees
from HogQLLexer import HogQLLexer
from HogQLParser import HogQLParser
from HogQLParserListener import HogQLParserListener


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
        default_query = "select *, toStartOfMonth(foo) as bar, (select bla), (case when 1 < 2 then 'string' else 'strang' end) from events"
        print(f"Default query: {default_query}\n")
        print(f"Enter a query to parse, or leave blank to parse the default")
        input_stream = InputStream(input(f"? ") or default_query)

    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    tree = parser.query()
    printer = KeyPrinter()
    walker = ParseTreeWalker()
    walker.walk(printer, tree)
    print(Trees.toStringTree(tree, None, parser))


if __name__ == "__main__":
    main(sys.argv)
