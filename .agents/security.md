# Security guidelines for agents

## SQL Security

- **Never** use f-strings with user-controlled values in SQL queries - this creates SQL injection vulnerabilities
- Use parameterized queries for all VALUES: `cursor.execute("SELECT * FROM t WHERE id = %s", [id])`
- Table/column names from Django ORM metadata (`model._meta.db_table`) are trusted sources
- For ClickHouse identifiers, use `escape_clickhouse_identifier()` from `posthog/hogql/escape_sql.py`
- When raw SQL is necessary with dynamic table/column names:

  ```python
  # Build query string separately from execution, document why identifiers are safe
  table = model._meta.db_table  # Trusted: from Django ORM metadata
  query = f"SELECT COUNT(*) FROM {table} WHERE team_id = %s"
  cursor.execute(query, [team_id])  # Values always parameterized
  ```

## HogQL Security

HogQL queries use `parse_expr()`, `parse_select()`, and `parse_order_expr()`. Two patterns exist:

**Vulnerable pattern** - User data interpolated INTO a HogQL template:

```python
# User data embedded in f-string - can escape context!
parse_expr(f"field = '{self.query.value}'")  # VULNERABLE
```

**Safe patterns**:

```python
# User provides ENTIRE expression - no context to escape
parse_expr(self.query.expression)  # SAFE - HogQL parser validates syntax

# User data wrapped in ast.Constant placeholder
parse_expr("{x}", placeholders={"x": ast.Constant(value=self.query.field)})  # SAFE
```

**Why direct pass-through is safe**: When users provide the entire HogQL expression (not data embedded in a template), there's no string context to escape from. The HogQL parser validates syntax and rejects malformed input.

**Sanitizers** (for use in placeholders):

- `ast.Constant(value=...)` - wraps values safely
- `ast.Tuple(exprs=...)` - for lists of values

## Semgrep Rules

Run `semgrep --config .semgrep/rules/hogql-no-fstring.yaml .` to check for HogQL injection issues.

Two rules:

1. `hogql-injection-taint` - Flags user data (`self.query.*`, etc.) interpolated into f-strings passed to parse functions (HIGH confidence)
2. `hogql-fstring-audit` - Flags all f-strings in parse functions for manual review (LOW confidence)

**When semgrep flags your code:**

- If user data is interpolated into f-string → wrap with `ast.Constant()` in placeholders
- If f-string uses safe values (loop index, enum, dict lookup) → add `# nosemgrep: <rule-id>` with explanation

**Running tests:**

```bash
# Local install
semgrep --test .semgrep/rules/

# Or via Docker
docker run --rm -v "${PWD}:/src" semgrep/semgrep semgrep --test /src/.semgrep/rules/
```
