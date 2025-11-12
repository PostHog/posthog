# LIKE ANY Implementation for HogQL

This document describes the implementation of the `LIKE ANY` pattern in HogQL, following Snowflake's syntax.

## Feature Overview

The `LIKE ANY` operator allows matching a value against multiple patterns:

```sql
SELECT * FROM events WHERE event_name LIKE ANY ('this_%', 'that_%')
```

This is expanded to:
```sql
SELECT * FROM events WHERE event_name LIKE 'this_%' OR event_name LIKE 'that_%'
```

## Implementation Status

### Completed ✅

1. **Grammar Definition** (`posthog/hogql/grammar/HogQLParser.g4`):
   - Added grammar rule for `LIKE ANY` and `ILIKE ANY` with `NOT` variants
   - Line 207: `| columnExpr NOT? (LIKE | ILIKE) ANY LPAREN columnExprList RPAREN # ColumnExprLikeAny`

2. **Parser Visitor** (`posthog/hogql/parser.py`):
   - Implemented `visitColumnExprLikeAny()` method (lines 922-948)
   - Expands to OR operations for positive matches
   - Expands to AND operations for negated matches
   - Handles edge cases (empty list, single pattern)

3. **Manual Python Parser Updates**:
   - Added `ColumnExprLikeAnyContext` class (`posthog/hogql/grammar/HogQLParser.py`)
   - Added visitor method stub (`posthog/hogql/grammar/HogQLParserVisitor.py`)

4. **Comprehensive Tests**:
   - Parser tests in `posthog/hogql/test/_test_parser.py::test_like_any`
   - Integration tests in `posthog/hogql/test/test_query.py::test_like_any_operators`
   - Tests cover: LIKE, ILIKE, NOT LIKE, NOT ILIKE, empty lists, null handling

### Required to Complete ⚠️

**CRITICAL**: The grammar parsers need to be regenerated for this feature to work:

1. **Install ANTLR 4.13.2**:
   ```bash
   # See posthog/hogql/grammar/README.md for installation instructions
   ```

2. **Regenerate Python Parser**:
   ```bash
   pnpm run grammar:build:python
   ```

3. **Regenerate C++ Parser** (primary parser used in production):
   ```bash
   pnpm run grammar:build:cpp
   ```

4. **Rebuild C++ Extension**:
   ```bash
   pip install ./common/hogql_parser
   ```

5. **Run Tests**:
   ```bash
   # Parser tests
   pytest posthog/hogql/test/_test_parser.py::TestParser::test_like_any -xvs

   # Integration tests
   pytest posthog/hogql/test/test_query.py::TestHogQLQuery::test_like_any_operators -xvs
   ```

## Supported Patterns

### Basic Usage
- `expr LIKE ANY (pattern1, pattern2, ...)`
- `expr ILIKE ANY (pattern1, pattern2, ...)` (case-insensitive)
- `expr NOT LIKE ANY (pattern1, pattern2, ...)`
- `expr NOT ILIKE ANY (pattern1, pattern2, ...)`

### Semantics
- **Positive match** (`LIKE ANY`): Returns true if expr matches ANY of the patterns (OR logic)
- **Negated match** (`NOT LIKE ANY`): Returns true if expr matches NONE of the patterns (AND logic)
- **Empty list**: Returns false for positive match, true for negated match
- **NULL handling**: Returns 0 (false) if expr is NULL

### Examples

```sql
-- Match events starting with 'page_' or 'click_'
SELECT * FROM events
WHERE event_name LIKE ANY ('page_%', 'click_%')

-- Case-insensitive match
SELECT * FROM events
WHERE event_name ILIKE ANY ('HELLO%', 'WORLD%')

-- Exclude events
SELECT * FROM events
WHERE event_name NOT LIKE ANY ('internal_%', 'test_%')
```

## Files Modified

1. `posthog/hogql/grammar/HogQLParser.g4` - Grammar definition
2. `posthog/hogql/parser.py` - AST visitor implementation
3. `posthog/hogql/grammar/HogQLParser.py` - Generated parser (manual patch)
4. `posthog/hogql/grammar/HogQLParserVisitor.py` - Generated visitor (manual patch)
5. `posthog/hogql/test/_test_parser.py` - Parser tests
6. `posthog/hogql/test/test_query.py` - Integration tests

## Notes

- Implementation follows the BETWEEN operator pattern in HogQL
- No new AST nodes were created; the feature expands directly to OR/AND of CompareOperation nodes
- This keeps the implementation simple and reuses existing infrastructure
- The expansion happens during parsing, so no special handling is needed in the printer or resolver
