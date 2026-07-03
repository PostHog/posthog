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

## Secrets & key management

`SECRET_KEY` already backs Django session/CSRF signing and is the legacy default for several other keys. Treat it as load-bearing and frozen — every new signing/encryption need gets its own key, rotatable and per-environment from the start.

- **Don't extend `SECRET_KEY` to new purposes.** Do not add code that reads `settings.SECRET_KEY` (or derives keys from it) for a new job. Mint a dedicated setting in `posthog/settings/` read from its own env var — e.g. `<PURPOSE>_SIGNING_KEY` / `<PURPOSE>_SECRET_KEYS`. A genuinely new purpose must NOT fall back to `SECRET_KEY`; fail closed when unprovisioned instead. Canonical example: `RECORDING_API_JWT_SECRET` (`posthog/settings/session_replay_v2.py`) — no `SECRET_KEY` default, empty in prod so only designated minters can sign. (Older keys like `JWT_SIGNING_KEY`, `TEMPORAL_SECRET_KEY`, `FLAGS_SECRET_KEYS` default to `SECRET_KEY` for self-hosted back-compat; that is migration debt, not the pattern to copy for new keys.)
- **Support rotation from day one.** Read the key as a list, newest first: the first element signs/encrypts, all elements are tried for verify/decrypt. Prefer a single comma-separated env var (`KEY="<new>,<old>"`) parsed with `get_list()` — the Fernet `new,old` convention. Examples: `RECORDING_API_JWT_SECRET` (`recording_api_jwt.py`), `FLAGS_SECRET_KEYS` (`encrypted_flag_payloads.py`). For encryption use `MultiFernet` (encrypt with first, decrypt with any) — see `posthog/helpers/encrypted_fields.py`. Encrypting data at rest? ship a re-encryption path that re-wraps onto the primary key, like `posthog/management/commands/reencrypt_fields.py`. The primary + `_FALLBACKS` pair (`JWT_SIGNING_KEY` / `JWT_SIGNING_KEY_FALLBACKS`) is the older two-var variant; single-var comma-separated is preferred for new keys.
- **Unique value per environment — including prod US and prod EU.** Never share a key value across environments; provision each (dev, prod-US, prod-EU) independently so one region can rotate without breaking another and a leak in one doesn't compromise the rest. Enforced at provisioning, not in code — so never hardcode a shared prod default. Fail closed when a prod key is unset (mirror the `SECRET_KEY` startup guard in `posthog/settings/access.py` and `RECORDING_API_JWT_SECRET`'s empty-in-prod default).
- **Don't extend `INTERNAL_API_SECRET` to new service-to-service calls.** It's a single fleet-wide shared secret already trusted by many services across Django, Node, and Rust — one leak reaches all of them — so it must not grow new callers or protected endpoints (it's being actively retired edge-by-edge; adding one moves it backwards). For a new internal call, in order of preference: (1) **mint a scoped JWT (strongly preferred)** — a dedicated per-audience signing key (never `INTERNAL_API_SECRET`/`SECRET_KEY`/`JWT_SIGNING_KEY`) with claims pinning the token to its team and operation, verified per-route; canonical example `RECORDING_API_JWT_SECRET` (mint in `posthog/session_recordings/recordings/recording_api_jwt.py`, verify in `nodejs/src/session-replay/recording-api/auth.ts`). (2) If a JWT genuinely doesn't fit, **a dedicated static secret** scoped to that one caller→callee pair (`<PURPOSE>_API_SECRET`, its own env var, rotatable, empty-in-prod-fail-closed) — never reuse `INTERNAL_API_SECRET`. The goal is blast radius: no single "master" credential that authenticates to a dozen services — a scoped JWT limits a leak to one team + operation; a dedicated secret limits it to one hop.

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
