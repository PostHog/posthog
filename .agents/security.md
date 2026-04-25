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

## IDOR Test Coverage

All tenant-scoped DRF viewsets with detail endpoints have automated cross-team IDOR coverage via `posthog/test/test_idor_coverage.py`. The test walks `posthog.api.router.urls` at collection time, generates one test per viewset, and verifies that an attacker (authenticated in team A) hitting the detail URL with a victim's resource id (from team B) receives 403/404/405 — never the victim's data.

Two classes of IDOR are covered:

- **Cross-team detail access** (`test_cross_team_get_detail` / `_patch_detail` / `_delete_detail`) — attacker hits the detail URL with the victim's pk on their own root URL. Verifies queryset scoping.
- **Writable FK in PATCH** (`test_cross_tenant_fk_in_patch`) — attacker PATCHes their **own** resource with a body that smuggles a victim's tenant FK pk into a writable serializer field. Verifies the field's queryset is scoped (e.g., via `TeamScopedPrimaryKeyRelatedField`) so the cross-tenant FK is rejected. The framework discovers writable tenant FKs from each viewset's serializer via `posthog/test/idor/fk_discovery.py`; tenant-scoped target models are pulled from `.semgrep/rules/idor-team-scoped-models.yaml` to avoid drift. Three FK shapes are detected:
  - **Explicit** — `serializers.PrimaryKeyRelatedField(...)` (and subclasses).
  - **Implicit** — `<thing>_id = IntegerField()` / `UUIDField()` / `CharField()`, where `Meta.model._meta.get_field('<thing>')` resolves to a `ForeignKey`. Common in older serializers that hand-roll validation in `validate()`.
  - **M2M** — `PrimaryKeyRelatedField(many=True, ...)` (or M2M model fields surfaced as `ManyRelatedField`). PATCH replaces the M2M set; the test sends `[victim_pk]` and verifies the related manager doesn't include it. Empty-list edge case: PATCHing `[]` clears the M2M, so tests run on a freshly-built attacker-owned instance to avoid order-dependence.

- **Writable FK in POST** (`test_cross_tenant_fk_in_post`) — attacker POSTs a brand-new resource into their own team's list URL with a body that smuggles a victim's tenant FK pk. Catches the IDOR shape where a FK is **only writable at create time** and becomes immutable afterwards (e.g., `Node.dag`, `PluginConfig.plugin`) — these slip past the PATCH variant entirely. Body construction has two layers:
  - **Generic synthesis** (`body_factory.build_minimal_post_body`) — walks the serializer's required, writable fields and fills sensible defaults (CharField → sentinel, ChoiceField → first choice, FK → attacker-owned instance pk via `build_minimal_instance`). Optional fields are omitted to avoid tripping unrelated validators.
  - **Per-viewset registry** (`post_body_fixtures.register_post_body`) — explicit factories for serializers where introspection can't satisfy custom `validate()` methods or shape constraints (e.g., `MessageTemplateSerializer` requires `content.email.subject` if `type='email'`).

  When body synthesis can't satisfy a serializer (`BodyUnfillable`), the test skips with a hint rather than asserting a false signal. 5xx responses also skip — they're latent server bugs, not data leaks. To skip a viewset entirely (POST disabled, custom permissions, side-effect-heavy create), add an entry to `IDOR_FK_POST_SKIP_LIST` in `posthog/test/idor/skip_list.py` with one of `POST_NOT_ALLOWED`, `BODY_SYNTHESIS_INFEASIBLE`, `INTENTIONAL_CROSS_TENANT_FK`, `REQUIRES_FILESYSTEM_OR_TEMPORAL`.

**When you add a new tenant-scoped viewset:**

Your PR will fail CI via `.github/scripts/check-idor-test-coverage.py` unless the viewset is one of:

1. **Auto-tested** — the default. The viewset inherits from `TeamAndOrgViewSetMixin`, uses `lookup_field` in `{"pk", "id"}`, and its model can be auto-instantiated via `posthog/test/idor/factory.py::build_minimal_instance`. No code changes needed.
2. **Covered by a fixture** — if the model has required FKs or custom validation the auto-factory can't satisfy, add a factory to `posthog/test/idor/fixtures.py` keyed by `app_label.ModelName`.
3. **Explicitly skipped** — if the viewset has a custom `lookup_field`, is a tenant-root resource (Organization/Team/Project itself), has no model, or is a legacy flat-URL viewset, add an entry to `posthog/test/idor/skip_list.py` with a documented category + reason.

**When you add a new writable FK to a serializer:**

`test_cross_tenant_fk_in_patch` automatically picks up any writable `PrimaryKeyRelatedField` (or one-level nested `ModelSerializer`) whose target model is in the semgrep tenant-scoped allowlist. You don't need to do anything for the auto-coverage.

If the field is **intentionally** cross-tenant (rare, e.g., a global system reference), or your viewset has no writable tenant FK and you want to silence the parametric, add an entry to `IDOR_FK_PATCH_SKIP_LIST` in `posthog/test/idor/skip_list.py` with one of these categories:

- `INTENTIONAL_CROSS_TENANT_FK` — the FK is meant to span tenants (document the threat model).
- `NO_WRITABLE_TENANT_FK` — discovery returns nothing actionable; the entry is documentation that something _was_ checked.

Stale entries (skip-list keys that no longer match a discovered viewset) fail CI. Defense in depth: the framework still tests fields that already use `TeamScopedPrimaryKeyRelatedField` / `OrgScopedPrimaryKeyRelatedField` so a regression in the scoping field itself is caught.

**Out-of-scope IDOR shapes** (covered separately):

- **String-by-name cross-tenant lookups** (e.g., looking up a Dashboard by `name=` rather than `id=`). Best caught by a semgrep rule (`idor-implicit-fk-in-serializer`) or manual taint review.
- **CREATE bodies** (POST). Phase 5b will add body synthesis; until then, audit POST handlers manually when adding a new tenant-FK serializer field.

**Running locally:**

```bash
# The full IDOR test suite
hogli test posthog/test/test_idor_coverage.py

# Just the FK-in-PATCH variant
hogli test posthog/test/test_idor_coverage.py -k test_cross_tenant_fk_in_patch

# The coverage check (same script CI runs)
python .github/scripts/check-idor-test-coverage.py

# Pure unit tests (no Django boot)
python -m pytest posthog/test/idor/test_url_structure.py posthog/test/idor/test_fk_discovery.py posthog/test/idor/test_fk_target_models.py posthog/test/idor/test_fk_canary.py
```
