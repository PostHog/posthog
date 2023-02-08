## How to generate source code files from grammar

Grammar is located inside `HogQLLexer.g4` and `HogQLParser.g4` files.

To generate source code you need to install locally the `antlr` binary:

```bash
brew install antlr
```

or this piece of art if you're using bash on ubuntu for quick access:

```bash
export ANTLR_VERSION=4.11.1

sudo apt-get install default-jre
mkdir antlr
cd antlr
curl -o antlr.jar https://www.antlr.org/download/antlr-$ANTLR_VERSION-complete.jar
export PWD=`pwd`
echo '#!/bin/bash' > antlr
echo "java -jar $PWD/antlr.jar \$*" >> antlr
chmod +x antlr
export CLASSPATH=".:$PWD/antlr.jar:$CLASSPATH"
export PATH="$PWD:$PATH"
```

Then either run

```bash
pnpm run grammar:build
```

Or mess around with:

```bash
cd posthog/hogql/grammar
antlr -Dlanguage=Python3 HogQLLexer.g4
antlr -visitor -Dlanguage=Python3 HogQLParser.g4
```

Original ClickHouse ANTLR grammar from: https://github.com/ClickHouse/ClickHouse/blob/master/utils/antlr/ClickHouseParser.g4

Changes with ClickHouse's grammar:
- removed all statements except for "select"
- raises an error if you run some ClickHouse SQL query features that are not implemented yet (ever changing list, check the code)
- supports placeholders like "team_id = {val1}"
