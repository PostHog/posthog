## How to generate source code files from grammar

Grammar is located inside `HogQLLexer.g4` and `HogQLParser.g4` files.

To generate source code you need to install locally the `antlr4` binary:

```
cd posthog/hogql/grammar

brew install antlr
pip install antlr4-python3-runtime
antlr4 -Dlanguage=Python3 HogQLLexer.g4
antlr4 -visitor -Dlanguage=Python3 HogQLParser.g4
python ParserTest.py
```

Original from https://github.com/ClickHouse/ClickHouse/blob/master/utils/antlr/ClickHouseParser.g4

Changes from ClickHouse's grammar:
- removed all statements except for "select"
