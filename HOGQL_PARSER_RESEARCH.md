# HogQL Parser: Full Architecture Research

## 1. The Grammar (Single Source of Truth)

The grammar lives in `posthog/hogql/grammar/` and is based on ClickHouse's ANTLR grammar, extended for HogQL-specific features:

| File                   | Purpose                                                         |
| ---------------------- | --------------------------------------------------------------- |
| `HogQLParser.g4`       | All parser rules (SELECT, expressions, statements, programs)    |
| `HogQLLexer.common.g4` | Shared lexer rules (keywords, operators, literals)              |
| `HogQLLexer.python.g4` | Python-specific lexer header (helper methods for tag detection) |
| `HogQLLexer.cpp.g4`    | C++-specific lexer header (same helpers in C++)                 |

Key grammar extensions beyond ClickHouse SQL:

- **Programs** (`program` rule): variables, functions, if/while/for, try/catch — the full "Hog" language
- **Template strings**: `f'Hello {name}'` interpolation
- **HogQLX**: JSX-like tag syntax `<SomeComponent prop={expr} />`
- **Placeholders**: `{expr}` for parameterized queries

### Top-level grammar rules

```text
program         → declaration* EOF
declaration     → varDecl | statement
varDecl         → LET identifier (: EQ expression)?
statement       → returnStmt | throwStmt | tryCatchStmt | ifStmt | whileStmt
                  | forInStmt | forStmt | funcStmt | varAssignment | block
                  | exprStmt | emptyStmt
expression      → columnExpr
select          → (selectSetStmt | selectStmt | hogqlxTagElement) ; EOF
selectStmt      → with? SELECT DISTINCT? top? columns from? arrayJoin? prewhere?
                  where? groupBy? having? window? orderBy? limitBy?
                  (limitOffset | offsetOnly)? settings?
columnExpr      → literals | functions | operators | casts | cases | subqueries
                  | lambdas | templates | ...
```

### Operator precedence (highest to lowest)

1. Unary negation (`-x`)
2. Array/tuple access, property access, type casting
3. `*`, `/`, `%`
4. `+`, `-`, `||` (concatenation)
5. Comparison (`=`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `IN`, `LIKE`, `REGEX`)
6. `IS NULL`
7. `NOT`
8. `AND`
9. `OR`
10. Ternary `? :`

### Lexer modes

The lexer uses multiple modes for context-sensitive tokenization:

- Default mode for SQL/Hog expressions
- `IN_TEMPLATE_STRING` for `f''` template strings
- `IN_FULL_TEMPLATE_STRING` for `F''` magic template strings
- `HOGQLX_TAG_OPEN` for XML-like tag attributes
- `HOGQLX_TAG_CLOSE` for closing tags
- `HOGQLX_TEXT` for content within tags

## 2. Three Compilation Targets From One Grammar

The grammar compiles to **three targets** using ANTLR 4.13.2:

```text
HogQLParser.g4 + HogQLLexer.*.g4
        │
        ├─► Python target  → posthog/hogql/grammar/HogQLParser.py, HogQLLexer.py
        │   (pnpm run grammar:build:python)
        │
        ├─► C++ target     → common/hogql_parser/HogQLParser.cpp, HogQLLexer.cpp
        │   (pnpm run grammar:build:cpp)
        │
        └─► WASM target    → (same C++ files, compiled via Emscripten)
            (pnpm --filter=@posthog/hogql-parser build)
```

The build concatenates the language-specific lexer header with the common lexer at build time:

```bash
cat HogQLLexer.python.g4 > HogQLLexer.g4
tail -n +2 HogQLLexer.common.g4 >> HogQLLexer.g4
antlr -Dlanguage=Python3 HogQLLexer.g4
```

## 3. Three Parser Backends (Python Side)

`posthog/hogql/parser.py` dispatches to one of three backends via the `RULE_TO_PARSE_FUNCTION` dict (line 52):

| Backend           | How it works                                                                | Speed   | Use case                       |
| ----------------- | --------------------------------------------------------------------------- | ------- | ------------------------------ |
| `"cpp"` (default) | C++ extension builds Python AST objects directly via CPython API            | Fastest | Production                     |
| `"cpp-json"`      | Same C++ code outputs JSON string, `json_ast.py` deserializes to Python AST | Medium  | Cross-platform, testing parity |
| `"python"`        | Pure Python ANTLR runtime + `HogQLParseTreeConverter` visitor               | Slowest | Development/debugging fallback |

Entry points:

- `parse_expr(expr, placeholders, start, backend)` — single expression
- `parse_select(statement, placeholders, backend)` — SELECT statement
- `parse_order_expr(order_expr, placeholders, backend)` — ORDER BY expression
- `parse_program(source, backend)` — full Hog program

## 4. The C++ → Python Bridge (`parser_python.cpp`)

The default `"cpp"` backend is a CPython extension module. The key class is `HogQLParseTreeConverter` in `common/hogql_parser/parser_python.cpp`:

- It's an ANTLR `BaseVisitor` that walks the parse tree
- Instead of returning C++ data structures, it constructs **Python objects directly** via the CPython API
- `build_ast_node("Constant", "{s#:N}", "value", ...)` calls `PyObject_GetAttrString(state->ast_module, "Constant")` to get the Python class, then calls it with kwargs
- The `parser_state` struct (in `parser_python.h`) holds cached references to `posthog.hogql.ast`, `posthog.hogql.base`, and `posthog.hogql.errors` modules

This means the C++ backend produces the exact same `ast.Constant`, `ast.SelectQuery`, etc. Python dataclass instances as the pure-Python backend, just much faster.

## 5. The C++ → JSON Bridge (`parser_json.cpp`)

`parser_json.cpp` contains `HogQLParseTreeJSONConverter` — a second ANTLR `BaseVisitor` that outputs a custom `Json` object. This JSON format is used by:

- The `"cpp-json"` Python backend (deserialized by `json_ast.py`)
- The WASM build (returned as JSON strings to JavaScript)

The JSON format uses a `"node"` key to identify AST node types:

```json
{
  "node": "ArithmeticOperation",
  "op": "+",
  "left": { "node": "Constant", "value": 1 },
  "right": { "node": "Constant", "value": 2 }
}
```

## 6. The WASM Parser (`parser_wasm.cpp`)

`parser_wasm.cpp` `#include`s `parser_json.cpp` directly (line 20), then wraps each function with WASM error handling and Emscripten bindings:

```cpp
EMSCRIPTEN_BINDINGS(hogql_parser) {
  function("parseExpr", &parse_expr);
  function("parseSelect", &parse_select);
  function("parseOrderExpr", &parse_order_expr);
  function("parseFullTemplateString", &parse_full_template_string);
  function("parseProgram", &parse_program);
  function("parseStringLiteralText", &parse_string_literal_text_wasm);
}
```

Build flags: `SINGLE_FILE=1` (WASM embedded in JS), `MODULARIZE=1` + `EXPORT_ES6=1` (async factory function), `ALLOW_MEMORY_GROWTH=1`.

Published as `@posthog/hogql-parser` workspace package.

Usage from JavaScript:

```typescript
import createHogQLParser from '@posthog/hogql-parser'

const parser = await createHogQLParser()
const ast = JSON.parse(parser.parseExpr('1 + 2'))
```

## 7. AST Node Definitions

All AST nodes are Python dataclasses in `posthog/hogql/ast.py` and `posthog/hogql/base.py`:

```text
AST (base.py)
  ├─ Type — type system nodes
  ├─ Expr — expression nodes
  │   ├─ Constant(value)        — literals
  │   ├─ Field(chain)           — column references
  │   ├─ Call(name, args)       — function calls
  │   ├─ ArithmeticOperation    — +, -, *, /, %
  │   ├─ CompareOperation       — ==, !=, <, >, etc.
  │   ├─ And/Or(exprs)          — boolean logic
  │   ├─ Array/Tuple(exprs)     — collections
  │   ├─ Alias(expr, alias)     — AS clause
  │   ├─ SelectQuery            — SELECT statement
  │   └─ SelectSetQuery         — UNION, INTERSECT, EXCEPT
  └─ Declaration — statement nodes (var, if, while, for, function, etc.)
```

Each node has `start` and `end` optional int fields for character offset tracking.

## 8. Post-Parse Pipeline

After parsing produces an AST:

1. **Placeholder replacement** (`placeholders.py`): `{x}` placeholders substituted with provided AST nodes
2. **Type resolution** (`resolver.py`): Semantic analysis — resolves field references against database schema, assigns types to all expressions, creates query scopes
3. **Compilation/printing**: Resolved AST is compiled to ClickHouse SQL or Hog bytecode

## 9. Frontend WASM Usage (Current State)

The WASM parser is available as `@posthog/hogql-parser` in the workspace, but **the frontend barely uses it**. The only reference in frontend code is `jest.config.ts` (transform ignore pattern). The SQL utilities in `frontend/src/scenes/data-warehouse/editor/sql-utils.ts` do **manual regex-based SQL parsing** rather than using the WASM parser.

This means the frontend currently does naive string matching for SQL tasks (column extraction, table detection) instead of using the real grammar.

## 10. How to Add a New Grammar Rule

1. **Edit the grammar** — `HogQLParser.g4` for parser rules, `HogQLLexer.common.g4` for new tokens/keywords

2. **Regenerate both targets**:

   ```bash
   pnpm run grammar:build  # builds both Python and C++ targets
   ```

3. **Implement the visitor in all three backends**:
   - **Python**: `visitYourNewRule` in `HogQLParseTreeConverter` in `posthog/hogql/parser.py`
   - **C++ Python**: `visitYourNewRule` in `HogQLParseTreeConverter` in `common/hogql_parser/parser_python.cpp`
   - **C++ JSON**: `visitYourNewRule` in `HogQLParseTreeJSONConverter` in `common/hogql_parser/parser_json.cpp`

4. **Add AST node** (if needed) — `@dataclass` in `posthog/hogql/ast.py`

5. **Update the resolver** — `posthog/hogql/resolver.py` if new rule has new semantics

6. **Update JSON deserialization** — `json_ast.py` `NODE_MAP` if new AST node added

7. **CI check** — `.github/workflows/ci-hog.yml` runs `npm run grammar:build && git diff --exit-code`

## 11. Compatibility and Risks

| Concern                   | Status                                                       |
| ------------------------- | ------------------------------------------------------------ |
| Grammar parity            | Perfect — WASM and C++/Python use the same `.g4` grammar     |
| Parse tree visitor parity | Must be maintained manually across 3 implementations         |
| AST format parity         | JSON format shared between WASM and `cpp-json` backend       |
| Frontend adoption         | Low — WASM parser exists but frontend uses regex heuristics  |
| New rule workflow         | Requires updating 3 visitor implementations + AST + resolver |

The main friction point is **visitor implementation drift** — the three backends (`parser.py`, `parser_python.cpp`, `parser_json.cpp`) implement the same grammar independently. The `VISIT_UNSUPPORTED` macro in C++ and `NotImplementedError` in Python are safety nets. A `_compare_with_cpp_json` function in `parser.py` (line 96) randomly samples parses to verify backend equivalence.

## 12. Architecture Diagram

```text
                    ┌──────────────────────────┐
                    │  HogQLParser.g4 (grammar) │
                    │  HogQLLexer.*.g4          │
                    └────────┬─────────────────┘
                             │ antlr 4.13.2
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
    ┌───────────┐    ┌───────────┐    ┌───────────┐
    │ Python    │    │ C++ files │    │ C++ files │
    │ .py files │    │ (native)  │    │ (same)    │
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                │                │
          ▼                ▼                ▼
   ┌─────────────┐  ┌────────────┐  ┌──────────────┐
   │ Python      │  │ CPython    │  │ Emscripten   │
   │ ANTLR       │  │ Extension  │  │ WASM build   │
   │ Visitor     │  │ Module     │  │              │
   │ (parser.py) │  │            │  │              │
   └──────┬──────┘  └──┬────┬───┘  └──────┬───────┘
          │             │    │             │
          │     ┌───────┘    └──────┐      │
          ▼     ▼                   ▼      ▼
     ┌────────────┐          ┌──────────────────┐
     │ Python AST │          │   JSON AST       │
     │ objects    │          │   (string)       │
     │ (direct)   │          │                  │
     └────────────┘          └────┬────────┬────┘
                                  │        │
                          ┌───────┘        └──────────┐
                          ▼                           ▼
                   ┌──────────────┐          ┌────────────────┐
                   │ json_ast.py  │          │ JS JSON.parse  │
                   │ deserialize  │          │ (frontend)     │
                   └──────┬───────┘          └────────────────┘
                          ▼
                   ┌──────────────┐
                   │ Python AST   │
                   │ objects      │
                   └──────────────┘
```

## 13. Key Files Reference

| File                                         | Purpose                                        |
| -------------------------------------------- | ---------------------------------------------- |
| `posthog/hogql/grammar/HogQLParser.g4`       | Parser grammar rules                           |
| `posthog/hogql/grammar/HogQLLexer.common.g4` | Shared lexer tokens                            |
| `posthog/hogql/grammar/HogQLLexer.python.g4` | Python-specific lexer                          |
| `posthog/hogql/grammar/HogQLLexer.cpp.g4`    | C++-specific lexer                             |
| `posthog/hogql/parser.py`                    | Entry points, backend dispatch, Python visitor |
| `posthog/hogql/ast.py`                       | AST node dataclass definitions                 |
| `posthog/hogql/base.py`                      | Base AST/Expr/Type classes + visitor pattern   |
| `posthog/hogql/resolver.py`                  | Semantic analysis, type resolution             |
| `posthog/hogql/visitor.py`                   | Visitor base classes for tree traversal        |
| `posthog/hogql/json_ast.py`                  | JSON ↔ Python AST deserialization             |
| `posthog/hogql/placeholders.py`              | Placeholder finding and replacement            |
| `posthog/hogql/errors.py`                    | Error hierarchy with position tracking         |
| `common/hogql_parser/parser_python.cpp`      | C++ visitor building Python objects            |
| `common/hogql_parser/parser_json.cpp`        | C++ visitor building JSON                      |
| `common/hogql_parser/parser_wasm.cpp`        | WASM bindings for JavaScript                   |
| `common/hogql_parser/CMakeLists.txt`         | C++/WASM build configuration                   |
| `common/hogql_parser/setup.py`               | Python C extension build                       |
| `common/hogql_parser/CONTRIBUTING.md`        | Development guide                              |
