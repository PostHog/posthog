# Security guidelines for agents

## Routing security fixes

**Security fixes land in `PostHog/posthog` by default.**
`PostHog/posthog-private` is only for severe vulnerabilities that need an embargo.
An embargo is expensive: team-security pauses the private sync, disables the merge queue, and ships the fix through the security sync flow.
Most security fixes do not justify that cost.

Before you create a branch or PR, choose the route:

- **The weakness exists only in an open, unmerged public PR:** fix it in that same PR before merge, including its tests. Do not open a private PR for it.
- **Severe vulnerability that needs an embargo:** use `PostHog/posthog-private` on a `security/` branch only when team-security agrees an embargo is necessary. Severe means an attacker can exploit live code today, without special access, to do serious harm. Examples are cross-tenant data access, authentication bypass, remote code execution, or exposure of credentials or secrets. Keep the finding, reproduction, and vulnerable paths in private channels until disclosure is approved.
- **Every other security fix:** open a normal PR in `PostHog/posthog`. This includes hardening, defense in depth, input validation, consistency fixes between code paths, access checks with low impact, issues that need privileged or same-team access, and missing rate limits.

A public security fix is a normal fix with a neutral description.
Describe what the change does, not how to exploit the old behavior.
Leave out step-by-step reproductions, payloads, and severity ratings from the title, description, commit messages, and test names.

Never create a branch, push, or open a PR in `PostHog/posthog-private` without the user's confirmation in the current conversation.
When you ask, say why the finding looks severe enough for an embargo.
If you are unsure whether a finding is severe enough, stop and ask the user before you push to either repo.
Do not choose the private repo only because a change touches access control, authentication, or another security-sensitive area, or only because a branch is named `security/`.

Follow the user's instructions about whether to create a branch, commit, push, or update a PR.

This section is about where the fix lands; the rest of this doc is about writing secure code.

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
- **Don't extend `INTERNAL_API_SECRET` to new service-to-service calls.** It's a single fleet-wide shared secret already trusted by many services across Django, Node, and Rust — one leak reaches all of them — so it must not grow new callers or protected endpoints (it's being actively retired edge-by-edge; adding one moves it backwards). For a new internal call, in order of preference: (1) **mint a scoped JWT (strongly preferred)** — a dedicated per-audience signing key (never `INTERNAL_API_SECRET`/`SECRET_KEY`/`JWT_SIGNING_KEY`) with claims pinning the token to its team and operation, verified per-route; use the shared machinery instead of hand-rolling: `ScopedServiceJwtPurpose` + `ScopedServiceJWTAuthentication` in `posthog/scoped_service_jwt.py` (Django mint/verify) and `ScopedServiceJwt` in `nodejs/src/cdp/utils/scoped-service-jwt.ts` (Node mint/verify); worked examples: the conversations ticket route (`products/conversations/backend/api/internal.py`) and its minting worker (`nodejs/src/cdp/async-functions/internal-api-call.ts`). (2) If a JWT genuinely doesn't fit, **a dedicated static secret** scoped to that one caller→callee pair (`<PURPOSE>_API_SECRET`, its own env var, rotatable, empty-in-prod-fail-closed) — never reuse `INTERNAL_API_SECRET`. The goal is blast radius: no single "master" credential that authenticates to a dozen services — a scoped JWT limits a leak to one team + operation; a dedicated secret limits it to one hop.

## Authentication classes

In a test marked with `@covers_authentication(<class>)`, when the class returns a `User`, the same request runs again with that user deactivated and then blocked, and the test fails if either run lets the user in.

- **Mark one test per DRF authentication class.** Decorate a test that authenticates a request through the class with `@covers_authentication(<class>)` from `posthog/test/authentication_checks.py`. `test_authentication_credential_types.py` fails when a class has no marked test.
- **Refuse inactive and blocked users.** Filter on `is_active` and call `refuse_blocked_account()`.
- **A new Django authentication backend** must return `None` from `get_user()` for an inactive user. `TestSessionBackendsRefuseInactiveUsers` checks every backend in `AUTHENTICATION_BACKENDS`.

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

## Deserialization (pickle)

**Do not add new `pickle` usage.**
Unpickling bytes that any other process could influence is arbitrary code execution — the pickle stream can name any importable callable and pass it arguments.
This applies to the equivalents too: `cPickle`, `cloudpickle`, `dill`, `marshal`, `shelve`, `joblib`, `pandas.read_pickle`, and `numpy.load(..., allow_pickle=True)`.
CI already fails on new pickle: the `avoid-pickle` rule from the `p/security-audit` Semgrep pack runs as a blocking rule in the security semgrep jobs (see `.github/workflows/ci-security.yaml`), so introducing one is a hard stop, not a warning.
Pickle can also appear without the word `pickle`: Django's default cache backend (`cache.set` / `cache.get`) pickles values transparently, so treat the cache as a pickle boundary and only store JSON-serializable values in it.

**Use JSON instead.**
For plain data, use `json`.
For typed objects, use a schema-validated (de)serializer that constructs only declared types — Pydantic `model.model_dump_json()` / `Model.model_validate_json(...)` is the house default (the AI conversation stream in `ee/hogai/stream/redis_stream.py` uses exactly this).
Anything that crosses a process, cache, queue, or the wire must be JSON-shaped, not pickle-shaped.

**If pickle is genuinely unavoidable** — almost always an existing cross-language or cross-version format contract you can't change unilaterally (e.g. Django's cache backend and the Rust services both wrap JSON in pickle) — it must satisfy all of:

1. **Internal, self-generated data only.** Never unpickle anything a user, tenant, or untrusted service could write. "Internal Redis" is not a trust boundary — anyone with write access to the datastore controls the bytes.
2. **A restricted `pickle.Unpickler`.** Override `find_class` to a strict allowlist of the exact classes you expect, or — when the payload is JSON-shaped (str/dict/list/number/bool/None) — a deny-all `find_class` that raises for everything. JSON-shaped values deserialize through dedicated opcodes that never call `find_class`, so denying it blocks every code-execution path while still loading your data.
3. **A justified `# nosemgrep`** on the line immediately before the call (per the repo nosemgrep convention), stating why it's safe.

Reference implementations:

```python
# Deny-all: the payload is only ever a JSON string / dict, so no class is ever legitimate.
# posthog/storage/auth_token_cache_verifier.py -> _JsonOnlyUnpickler
class _JsonOnlyUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        raise pickle.UnpicklingError(f"refusing to unpickle disallowed global {module}.{name}")

# Allowlist: reconstruct only our own catalog classes.
# posthog/hogql/database/database.py -> _CatalogUnpickler
class _CatalogUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if module.startswith(_ALLOWED_PREFIXES) or module in _ALLOWED_MODULES:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"refusing to unpickle disallowed global {module}.{name}")
```

## Semgrep Rules

Run `semgrep --config .semgrep/rules/security/ .` to check for injection issues.

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
semgrep --test .semgrep/rules/security/

# Or via Docker
docker run --rm -v "${PWD}:/src" semgrep/semgrep semgrep --test /src/.semgrep/rules/security/
```

## Outbound requests and SSRF

PostHog Cloud sends production egress through a Smokescreen proxy. On a code path that goes
through the proxy, treat raw SSRF, such as a request to an internal IP or to cloud metadata, as
mitigated. A code path that bypasses the proxy, and a self-hosted deployment, do not have this
control. A request that probes or trusts an attacker-controlled server is always in scope. The
SSRF rule in `.agents/skills/security-audit/SKILL.md` says which control is load-bearing.

## Out-of-band interaction domains

`posthog/security/crosslang/oob_domains.json` lists the services that capture out-of-band
interactions, such as Interactsh and Burp Collaborator, and the DNS rebinding services.

Today the guards only log a match. Nothing is refused yet.

The warehouse guards emit the `oob_domain` stage of `data_imports.host_check`, which carries
`team_id`, and the `oob_domain_resolved` stage when the caller resolved the host first. The HTTP
adapter emits `security.oob_domain_seen` and takes its team from the activity's bound log context.
`posthog/security/url_validation.py` emits the same event with no team at all, because no team is
in scope there, so those lines are attributable to a host and not to a project.

In Node, `validateHostnameIPLiteral` (`nodejs/src/common/utils/request.ts`) and `EmailValidationService.getSkipReason` emit `security.oob_domain_seen` too, under the guard `node_request` or `node_email_validation`.
Both read the hand-written mirror in `nodejs/src/common/utils/oob-domains.ts`, which a parity test holds against the JSON.
Both log `team_id`, the field the Python guards bind.
The email guard always has a team.
The request guard has one only when the fetch runs under `fetchAttribution`, as a CDP destination fetch and a recording export's stylesheet fetch do, and logs `team_id: null` for any other caller.
`noteOobDomain` logs one line per host, team and guard every 15 minutes, because a retrying destination would otherwise log per attempt.

The Rust guards call `common_dns::oob_domains::note_oob_domain` and emit `security.oob_domain_seen` under three guard names.
They read the hand-written mirror in `rust/common/dns/src/oob_domains.rs`, which a parity test holds against the JSON.
`note_oob_domain` takes the team as an `Option`, logs one line per host, team and guard every 15 minutes, and omits the `team_id` field rather than printing an empty one.
`cymbal_sourcemap` names the team on the source and sourcemap fetches, and omits it on a redirect hop, because one HTTP client serves every team.
`batch_import_s3_endpoint` always names the team, which the job model carries.
`common_dns_resolver` never names one: it fires inside the shared reqwest and Smithy resolvers, which no caller passes a team to.

Every check runs on cloud only, and each runs before its guard's own DNS resolution, because the lookup alone confirms the path to whoever runs the collaborator.

It stops the default scanner configuration. It does not stop a determined attacker, who points a
CNAME at the collaborator or runs their own server. The IP checks and the address pinning remain
the real controls.

## Content Security Policy

`CSPMiddleware` in `posthog/csp_middleware.py` attaches a policy to every HTML response.
Treat it as enforced.
team-security owns that file in `.github/CODEOWNERS`, so every policy change needs their approval.
A refused resource produces no user-visible error, so the feature simply does not work, and the only signal is a `$csp_violation` event in project 2.

Three policies exist, and a change lands in whichever one covers the page:

- **The app policy** governs every SPA page. On PostHog Cloud and in local development, it is enforced for every visitor, signed-in or not. A self-hosted install only reports it, because its violations reach nobody. Embeddable documents, such as shared dashboards, get the policy without `frame-ancestors`, because customers frame them on their own sites. Two routes in `REPORT_ONLY_ROUTES` stay report-only. The bare `/exporter` render document stays report-only, because a replay export can run an `eval` in a frame of the render, and an enforced policy would refuse it. It stays report-only until the caller of that `eval` is traced. `/external_surveys/<id>` stays report-only on a response that the survey view did not build.
- **The admin policy** governs `/admin/`. It is enforced for every staff member, so a mistake here breaks admin immediately.
- **A view may set its own policy.** The canvas artifact and the workflow asset endpoint do this to sandbox untrusted HTML. `CSPMiddleware` returns a response that already carries the header unchanged, so do not expect the app policy on those documents.

### What the app policy forbids

| You want to                     | The policy says                                                                                                                                                       |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Load a script from a new origin | Only `'self'`, our own CDNs, and a named list. Stripe, Turnstile and Unlayer are there because each vendor requires its own origin. Prefer serving the file yourself. |
| Call `eval` or `new Function`   | Refused. `wasm-unsafe-eval` permits WebAssembly compilation only.                                                                                                     |
| Start a worker                  | `'self'` and `blob:` only. Never `data:`: a `data:` worker body is code the policy cannot inspect.                                                                    |
| Load a font from a CDN          | Self-host it instead. A CDN font already caused a regression when the origin was removed.                                                                             |
| Submit a form                   | `'self'` plus the admin OAuth origin. The directive is checked on every hop of a redirect chain, so a same-origin action that redirects off-origin is refused.        |
| Set `<base href>`               | Refused. Chromium judges the assignment even on a detached document.                                                                                                  |

### Traps that have already cost us

- **A dependency can carry the origin.** Grep `node_modules` for the literal host before you call an origin unused. A font CDN was removed on the belief nothing used it, and a transitive dependency defaulted to it.
- **posthog-js wraps `fetch`, so an extension's request is reported with our bundle as the source file.** Never conclude a violation is ours from the source file alone. Corroborate with the blocked URL and the document.
- **A CSP report names the original URL, not the hop that failed.** For `form-action` and any redirected navigation, the blocked URL can be same-origin while the refusal happened later in the chain.
- **The Vite dev server cannot reproduce any of this.** It injects CSS as `<style>` blocks and emits absolute asset URLs, so paths that depend on a stylesheet's own href never run. Only the esbuild build matches production.

### Checking a change

Add the source to the policy that covers the document, which is not always `CSPMiddleware`.
An app or admin page takes the matching list in `CSPMiddleware`.
On PostHog Cloud, the app policy's `script-src`, `connect-src`, `style-src` and `font-src` name each PostHog host instead of `*.posthog.com`.
A script, stylesheet or font from another PostHog subdomain, or a request to one, needs its host in the lists that `CSPMiddleware` passes to `narrowed_app_policy()`.
Local runs, E2E runs and self-hosted installs keep the wildcards, so a missing host breaks only production.
On PostHog Cloud, each app document also sends a report-only policy that holds only `img-src`, without `https:` and with each PostHog host named instead of `*.posthog.com`.
It blocks nothing, and its reports (`$csp_version` 7) list the image hosts that only `https:` or `*.posthog.com` admits.
An image from another PostHog subdomain needs its host in the list in `img_src_shadow_policy()`, or each load of it reports.
Name a new image host in `img-src` anyway, so that removing `https:` later does not break it.
A canvas artifact takes `artifact_csp()` in `products/canvas/backend/contract.py`, and a workflow message asset takes the header its endpoint sets in `products/workflows/backend/presentation/views/hog_flow.py`.
`CSPMiddleware` returns a view-set header untouched, so widening the app policy does nothing for those two.
Say why the source is needed in a comment either way, then run `posthog/test/test_csp_middleware.py`.
The `csp-header-outside-csp-middleware` semgrep rule blocks a `Content-Security-Policy` header set anywhere else.
A new document that must carry its own policy needs team-security to add it to that rule's exceptions.
To see what the policy currently blocks, query `$csp_violation` events in project 2.
Filter to the current policy text and exclude browser extensions on both the source file and the blocked URL, or the result is mostly noise.
