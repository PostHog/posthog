## How to generate source code files from grammar

Grammar is located inside `HogQLLexer.g4` and `HogQLParser.g4` files.

To generate source code you need to install locally the `antlr4` binary:

```bash
brew install antlr
```

Then either run

```bash
pnpm run grammar:build
```

Or mess around with:

```bash
cd posthog/hogql/grammar
antlr4 -Dlanguage=Python3 HogQLLexer.g4
antlr4 -visitor -Dlanguage=Python3 HogQLParser.g4
```

Original ClickHouse ANTLR grammar from: https://github.com/ClickHouse/ClickHouse/blob/master/utils/antlr/ClickHouseParser.g4

Changes with ClickHouse's grammar:
- removed all statements except for "select"
- support aliases with a string literal "as '🍄'"
- strings can also be entered with double quotes, not just single quotes
- raises an error if you run some ClickHouse SQL query features that are not implemented yet (ever changing list, check the code)
- supports placeholders like "team_id = {val1}"