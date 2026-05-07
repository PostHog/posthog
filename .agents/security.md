# Security guidelines for agents

## Principle of Least Privilege

Default to the smallest permission, narrowest field set, and shortest scope that still works. If a change needs more access than what's already in place, stop and reconsider the design before widening it.

- **Default deny.** Start from no access and add what's required, rather than opening things up and trimming back.
- **Scope every queryset.** Filter by `team_id` (and `organization_id` where appropriate) so a request can only ever touch its own data.
- **Reuse existing permission and access-control classes** — don't write a looser variant to fit a new caller. If the existing class doesn't fit, that's a design conversation, not a quick relax.
- **Separate read and write checks.** "Can see" and "can modify" are different questions; don't let one imply the other.
- **Lock down ownership fields.** Mark `team`, `created_by`, `organization`, and similar fields as `read_only` on serializers. Set them server-side from request context, never from client input.
- **Expose the minimum on serializers.** Don't include tokens, secrets, internal IDs, or fields a caller doesn't need just because they exist on the model.
- **Gate admin and internal paths explicitly.** Use `is_staff`, organization roles, or feature flags — never rely on URL obscurity or "no one will hit this".
- **Background work runs with caller scope.** Celery tasks and Temporal activities should preserve the requesting user/team, not silently escalate to superuser.
- **Tokens and credentials: narrowest scope, shortest lifetime.** Don't widen an existing token's scope to fit a new use case — mint a new one. Never log secrets, never commit them.
- **Remove access in the same change as the feature.** When a role, endpoint, or capability goes away, delete its permissions and grants then and there. Dormant grants accumulate and become tomorrow's incident.

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
- `ast.Field(chain=[...])` - wraps identifiers (table names, column names) safely

## ORM Security

Django's `__` notation in ORM lookups allows FK traversal. If a user-controlled value is interpolated into a `.filter()`, `.exclude()`, or `Q()` dict key, an attacker can traverse relationships to exfiltrate sensitive fields (e.g. `user__password`, `team__api_token`).

**Vulnerable pattern** - Variable interpolated into filter key:

```python
# key is user-controlled — attacker can pass "user__password"
queryset.filter(**{f"{key}__icontains": value})  # VULNERABLE
```

**Safe patterns**:

```python
# Validate against an allowlist before use
ALLOWED_FIELDS = {"name", "email", "created_at"}
if key not in ALLOWED_FIELDS:
    raise ValueError(f"Invalid filter field: {key}")
queryset.filter(**{f"{key}__icontains": value})  # SAFE

# Hardcoded keys are always safe
queryset.filter(**{"name__icontains": value})  # SAFE
queryset.filter(name__icontains=value)  # SAFE
```

> **JSONField note:** If the first path segment is a JSONField (e.g. `detail__`), Django routes all subsequent `__` as JSON key lookups rather than FK traversals, which mitigates the risk. An allowlist is still recommended as defense in depth.

## Semgrep Rules

Run `semgrep --config .semgrep/rules/ .` to check for injection issues.

Three rules:

1. `hogql-injection-taint` - Flags user data (`self.query.*`, `self.$obj.$field`, etc.) interpolated into f-strings passed to parse functions (HIGH confidence)
2. `hogql-fstring-audit` - Flags all f-strings in parse functions for manual review (LOW confidence)
3. `orm-field-injection` - Flags variables interpolated into dict keys passed to `.filter()`, `.exclude()`, or `Q()` (MEDIUM confidence)

**When semgrep flags your code:**

- If user data is interpolated into an f-string HogQL template → wrap with `ast.Constant()` or `ast.Field(chain=[...])` in placeholders
- If a variable is used in an ORM filter key → validate against an allowlist of permitted field names
- If the code is safe (loop index, enum, dict lookup, JSONField prefix) → add `# nosemgrep: <rule-id>` with explanation

**Running tests:**

```bash
# Local install
semgrep --test .semgrep/rules/

# Or via Docker
docker run --rm -v "${PWD}:/src" semgrep/semgrep semgrep --test /src/.semgrep/rules/
```
