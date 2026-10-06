# HogQL language service

## Goal

The HogQL language service moves latency-sensitive SQL editor operations into a long-lived Go process. Its resident
catalog avoids rebuilding tables, views, and property metadata for every keystroke.

The service targets:

- low-single-digit-millisecond autocomplete on a warm catalog;
- a stable internal API for HogQL validation and, later, translation; and
- low PostHog overhead above ClickHouse execution time.

## Architecture

```text
Browser
  | authenticated PostHog request
  v
Django
  | resolves team membership and user permissions
  | publishes visible catalog with a scoped service JWT
  v
HogQL language service
  | selects the exact team and user catalog
  | parses and resolves entirely in memory
  v
Autocomplete or validation response
```

Django remains authoritative for authentication, team membership, entitlements, feature flags, and access-control
resolution. The Go service does not read PostHog permission tables or accept browser-selected identity without an
authenticated internal request.

The shared catalog excludes direct-connection table rows because those rows belong only to an explicit `connectionId` database.
This keeps a direct table's raw dotted name from replacing a synced table that resolves to the same catalog key.

Django adds resolver-confirmed `tableAliases` to the same permission-filtered catalog snapshot.
For example, a catalog can map `demo_postgres_orders` to `postgres.demo.orders` when both names resolve to the same visible warehouse table.
Aliases from another project or hidden tables are not published.
If a candidate is hidden or unresolvable, or a canonical name resolves to different metadata, Django abandons the publication and uses the Python path.
An alias must resolve to the same table object as exactly one exported canonical name; matching physical IDs alone do not establish equivalence.
An alias candidate that resolves unambiguously to another visible canonical table follows that effective resolver winner.
Nonrepresentable resolver collisions require a separate catalog contract before they can use the Go service.
Built-in `posthog.*` namespaces are outside this rollout.

## Query analysis

`internal/analysis` owns parsed statements, nested scopes, table and CTE bindings, and projected fields for validation and completion.
Each document belongs to one request and borrows that request's immutable catalog.
Statements initialize on demand, while CTE and aliased subquery projections share one budget across the document.
Validation retains diagnostic formatting, typo suggestions, and position-encoding conversion.

Completion replaces the identifier at the cursor with a placeholder and resolves the containing scope.
An empty query, whitespace, or the start of a statement offers SELECT and WITH, filtered by the typed prefix.
Completed comments can precede these starters; completion remains disabled inside strings and unfinished comments.
These suggestions do not carry a parser error for the unfinished statement.
After a completed JOIN ON condition, completion includes WHERE, including before an existing ORDER BY clause.
For example, `SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid |` offers WHERE at `|`.
Completion does not offer WHERE inside unfinished ON parentheses or between the bounds of BETWEEN.
Completion also keeps query clauses out of unfinished CASE expressions.
Before another JOIN at the same query scope, an ON condition offers only AND and OR as clause continuations while retaining applicable comparison operators.
For example, `SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid | JOIN persons AS p ON 1 = 1` offers AND and OR at `|`, but not WHERE, GROUP BY, ORDER BY, or LIMIT.
Nested JOINs, comments, strings, and later statements do not suppress a valid WHERE suggestion.
Other clauses already present after the cursor are not globally filtered from suggestions.
An incomplete cursor placeholder can still produce a `parseError` alongside these keyword suggestions.
Unquoted TRUE and FALSE are boolean literals, regardless of case, and validation does not look them up as fields.
For example, `SELECT uuid FROM events WHERE TRUE AND NOT FALSE` validates without unknown-field errors.
Expression completion offers TRUE and FALSE, including when typing `tr` or `fa` after a comparison operator.
Quoted or qualified names such as `events.TRUE` remain field references and require a matching catalog field.
CTE and aliased `FROM` subquery suggestions contain their projected output names, including aliases and wildcard expansion.
Direct field projections retain catalog types, and boolean literals project as `boolean`; other expression types remain unknown.
Qualified CTE completion also works before `FROM`, for example `WITH t AS (SELECT event FROM events) SELECT t.`.
Inner bindings take precedence, and sibling queries and statements do not contribute suggestions.
Validation checks aliased subquery output fields and continues to report only underlying catalog tables in `tableNames`.
Validation reports `duplicate_table` when a FROM or JOIN source reuses a table name or explicit alias in the same query scope.
Use distinct aliases for self-joins, for example `events AS e JOIN events AS other`.
This follows HogQL's resolver even when raw ClickHouse accepts an unaliased self-join.
The duplicate-name check is case-sensitive; separate nested queries and set-operation branches can reuse names.
Catalog table names, table aliases, and CTE names resolve by exact case, as in the Python resolver for ordinary tables.
Catalogs can contain both `events` and `Events`; each name retains its own fields, and validation lists both names when both are used.
With only `events` in the catalog, `SELECT properties FROM Events` reports `unknown_table`.
The same query is valid when an exact `Events` entry exists and exposes `properties`.
Table completion still matches prefixes without regard to case, so typing `EV` can suggest both names and inserts the selected name with its original case.
The optional `tableAliases` catalog map registers exact alternate spellings without duplicating field indexes.
For example, `"demo_postgres_orders": "postgres.demo.orders"` lets both names resolve to the fields on the canonical `tables` entry.
Validation retains the spelling from SQL in `tableNames`, and self-joins through two spellings keep separate source bindings.
Completion shows one spelling per canonical target. It prefers a matching canonical name and otherwise shows one matching alias.
CTEs shadow only their exact spelling, so a CTE named `demo_postgres_orders` does not hide `postgres.demo.orders`.
CTE shadowing and table-suggestion deduplication use exact names, so a CTE named `Events` does not hide the catalog table `events`.
Multi-part names retain their source identity when their parser-safe forms coincide, such as `a.b.c_d` and `a.b_c.d`.
Duplicate qualifiers do not establish property provenance, including inside CTE projections and qualified wildcards.
FROM and JOIN completion includes visible table CTEs before catalog tables, with `CTE` in the suggestion detail.
For an unquoted multi-part prefix, completion returns matching leaf tables with full labels and suffix-only insertion.
For example, `FROM postgres.` labels the result `postgres.demo.orders` and inserts `demo.orders`; `FROM postgres.demo.or` inserts `orders`.
Namespace components already present in SQL must match catalog case exactly, so insertion cannot produce an unresolved spelling.
Completion inside quoted path components and namespace-only suggestions remain follow-up work.
The service omits dotted candidates when any remaining component would require identifier quotes.
Monaco replaces the current word only through the cursor, so text after a mid-word cursor remains in the document.
CTE names follow the same scope, definition-order, and shadowing rules as relation lookup; scalar WITH aliases are not tables.
A visible CTE hides a catalog table with the same name, and pagination counts that name once.
CTE insertion quotes the whole name when needed, including names with dots.
When visible sources expose the same field name, unqualified completion returns one suggestion per source.
The label remains the field name, the detail includes its type and source, and insertion uses the qualified field, for example `e.uuid`.
An explicit table alias identifies its source, including separate aliases in a self-join; the table name and its alias do not create duplicate suggestions.
CTEs and aliased subqueries use the same rules, with identifier quoting for both the source and field.
Completion leaves `timestamp` unquoted, including qualified references such as `e.timestamp`; other keyword names still use conservative quoting.
Multi-part physical table paths use HogQL's implicit double-underscore alias, for example `postgres__synced__orders.synced_id`; an explicit alias takes precedence.
Equal field labels have a deterministic source order across completion pages.
Unqualified completion uses fixed-width global ranks for `sortText`, so client sorting preserves server order across pages even for labels containing punctuation.
Unique fields and already-qualified completion retain their existing details and insertion text.

Select aliases follow the resolution order in `posthog/hogql/resolver.py` (`visit_select_query` and `visit_alias`).
An explicit alias becomes visible after its defining SELECT item, so later items can reference it.
WHERE, PREWHERE, GROUP BY, HAVING, ORDER BY, named WINDOW definitions, and LIMIT expressions can reference all SELECT aliases in their query.
FROM and JOIN expressions cannot reference them, and aliases do not cross nested queries, CTE definitions, UNION branches, or statements.
UNION ALL, UNION DISTINCT, and EXCEPT branches resolve property containers and aliases from their own sources without inheriting another branch's property catalog.
Alias lookup is case-sensitive, as in the Python resolver; completion prefix matching remains case-insensitive.
An alias named `UUID` does not hide a source field named `uuid`; they can refer to different values.
An alias takes precedence over an unqualified field with the same name, while qualified field lookup still uses the relation.
Direct alias chains retain catalog types, and validation typo suggestions include visible aliases.

Direct property-container projections retain their original catalog namespace through CTEs, aliased subqueries, renamed fields, wildcard expansion, and visible SELECT aliases.
Completion and property-name validation use that same origin, rather than guessing from the projected name.
For example, `WITH recent AS (SELECT properties FROM events) SELECT recent.properties.$br FROM recent` suggests `$browser`.
A CTE named `events` that projects `persons.properties` uses the person property catalog, not the event catalog.
Renaming a container to `props` preserves its origin; projecting an individual property value does not preserve the whole container's namespace.

Case-variant aliases keep separate property origins:

```sql
SELECT e.properties.$browser, E.properties.email
FROM events AS e JOIN persons AS E ON 1 = 1
```

With those properties in the supplied catalog, both references validate.
Completion after `e.properties.$br` suggests the event property `$browser`, while `E.properties.em` suggests the person property `email`.
A reference to `E` does not resolve an alias declared only as `e`.
CTEs named `t` and `T` also retain separate projected fields and property origins.
An unrelated custom table named `Events` does not inherit the built-in event property catalog from its spelling.

Physical field completion borrows the catalog prefix index.
Derived projections have a shared limit of 16,384 fields before deduplication.
Field resolution also has a request-wide budget of 1,048,576 work units, counting relation visits and identifier bytes used for lookups and derived-field indexes.
Select-alias indexing, source enumeration, lookup, and field suggestion scans share that work budget.
Aliases of the same relation share a cached field index and one candidate entry for unqualified type resolution.
Completion returns HTTP 400 when either limit is exceeded; validation returns a `query_limit` diagnostic.
Derived qualified suggestions are sorted and deduplicated before pagination.

### Completion recovery

Completion first analyzes the query after replacing the identifier at the cursor.
If that parse fails, a query with complete CTE definitions can recover its outer scope when the SELECT list and FROM/JOIN sources remain parseable.
Recovery retains those source slices and discards the outer trailing clause, rather than guessing CTE fields or scanning aliases across scopes.
The shared analyzer still resolves projected fields, types, exact-case relation names, and known property origins.

With `|` marking the cursor, this incomplete query suggests `properties`:

```sql
WITH recent AS (SELECT uuid, properties FROM events)
SELECT recent.pro| FROM recent WHERE (
```

The cursor can also be inside the unfinished outer predicate:

```sql
WITH recent AS (SELECT properties AS props FROM events)
SELECT * FROM recent WHERE (recent.props.$br|
```

With `$browser` in the event property catalog, completion suggests that property.
A corresponding projection from `persons` uses the person property catalog instead.
The response keeps the original cursor-replaced `parseError`; validation still checks the original query and reports its syntax error.
Recovery never makes invalid SQL executable or changes the validation contract.
Supported trailing boundaries are WHERE, PREWHERE, GROUP BY, HAVING, ORDER BY, and LIMIT.

Recovery preserves SELECT aliases when their defining SELECT items survive parsing.
An outer predicate can see those aliases, but an earlier SELECT item cannot see a later alias.
The recovered cursor position preserves that distinction, including when the original cursor falls inside the discarded clause.
Recovered analysis uses the existing projection and field-lookup work limits.

For a single SELECT without WITH, the existing fallback recovers only a parseable FROM clause and does not reconstruct discarded SELECT aliases.
Neither fallback replaces successfully parsed bindings.

An unfinished block comment returns a parser error instead of blocking completion or validation.
For example, `WITH recent AS (SELECT uuid FROM events) SELECT recent.uuid FROM recent WHERE /* unfinished` produces a `syntax_error` validation diagnostic.
Completion before that comment returns a `parseError` without recovering CTE field suggestions; completion inside the comment remains disabled.
Closed block comments and line comments at end of input remain valid.

### Recovery and remaining work

- Multi-part normalization supports unquoted table paths after `FROM` and `JOIN`. Separately quoted path components and multi-part paths in comma-separated sources remain unsupported. Replacing the regular-expression normalization with token-aware handling is follow-up work.
- Source-specific case-insensitive relation lookup remains unsupported. Python catalog nodes can opt in, for example for Snowflake, but the Go catalog payload does not carry that per-node flag. Supporting it requires publishing the metadata and implementing exact-match-first, opt-in fallback without merging distinct names. The service requires exact relation names until then; autocomplete prefix matching remains case-insensitive.
- Physical field and property-key case sensitivity remain separate from relation-name resolution. This layer does not claim complete identifier-case parity with the Python resolver.
- CTE recovery requires complete CTE definitions and a parseable outer SELECT/FROM prefix. Broken CTE bodies, missing CTE-closing parentheses, and incomplete SELECT or JOIN sources remain unsupported because they do not establish a reliable projected schema. Recovering those forms requires separate structural recovery for each damaged scope.
- Recovery does not target a cursor inside a CTE definition or FROM/JOIN source section. It also rejects queries with any nested SELECT in the outer query, including an intact FROM subquery or predicate subquery. Per-scope recovery must first preserve cursor ownership and alias visibility without importing sibling bindings.
- Set-operation and multi-statement recovery, scalar WITH declarations, and unterminated quoted tokens or comments remain excluded. These need separate statement/branch selection and lexical recovery rules before the service can infer bindings safely.
- Property provenance covers direct containers only. Computed JSON expressions, nested JSON schemas, conflicting sources, and duplicate projected names do not establish a namespace. Completion suppresses property suggestions and validation skips property-name checks when the origin is unknown. Expression inference and ambiguous-column diagnostics remain follow-up work; duplicate source names produce `duplicate_table`.
- Projecting a nested virtual container such as `e.person.properties AS props` does not retain provenance. Model virtual-table traversal before enabling those projected namespaces; existing direct physical property paths remain available.
- Single-SELECT recovery without WITH retains only FROM bindings and does not guess discarded aliases. Extending SELECT-alias recovery there requires preserving its SELECT list and visibility positions as the CTE-aware path does.
- SELECT-alias property provenance follows the existing visibility and case-sensitive precedence rules. An alias without a known container origin suppresses property-owner fallback; it does not inherit a namespace from a name such as `person` or `properties`.
- Scalar WITH aliases, aliases inside expressions, ARRAY JOIN aliases, QUALIFY, and duplicate SELECT-alias diagnostics remain follow-up work. Model their resolver order and parser support before extending the top-level SELECT alias index. For duplicate declarations, the index retains the first field and type, but property provenance becomes unknown once the duplicate declaration is visible; earlier references retain their original provenance.
- Validation skips field checks when a query has no known FROM bindings, including SELECT without FROM. Completion can still suggest its aliases. Add explicit empty-source scopes and distinguish unknown relations before enabling strict validation there.
- JOIN USING output coalescing and ambiguous unqualified-field diagnostics remain follow-up work. Completion offers each source's qualified field; it does not choose a join-wide value or change validation's ambiguity rules.
- CTE table-name suggestions in malformed FROM/JOIN clauses still require cursor replacement to produce parseable SQL. This recovery slice targets outer expression completion with intact sources; recovering incomplete source declarations needs its own scope and ambiguity checks.
- Unaliased `FROM` subquery outputs, completion inside quoted identifiers, expression type inference, and complete set-operation semantics remain follow-up work.
- Recursive CTEs, lateral subqueries, and full HogQL compiler parity are outside this layer. The service does not execute queries or fetch metadata during analysis.

## Isolation boundary

Every protected route requires both `team_id` and `user_id` in its path. Shared middleware converts those values into
one authorization struct used by JWT verification, rate limiting, catalog lookup, and request handlers.

The service keys its current catalog cache by that pair because the published snapshot contains user-filtered tables
and properties.

The transport JWT also binds the request to:

- one positive team ID;
- one positive user ID;
- one service audience;
- an explicit operation; and
- a short validity window.

An absent, invalid, expired, or evicted catalog fails closed. The service never falls back to another team or user's
catalog.

Before reading a request body, a bounded token bucket limits the direct peer address. After JWT verification, another
bounded bucket limits the authenticated team and user pair. The service ignores forwarded-IP headers because only
deployment infrastructure can define a trustworthy proxy chain.

A later implementation may store structural schema once per team and apply smaller user authorization overlays. The
team remains the primary isolation boundary in that model.

## Resident state

Catalog publication replaces the catalog and revision atomically. Readers observe either the previous complete
revision or the next complete revision.

The publication contract accepts this alias form:

```json
{
  "tables": {
    "postgres.demo.orders": { "type": "data_warehouse", "fields": {} }
  },
  "tableAliases": {
    "demo_postgres_orders": "postgres.demo.orders"
  },
  "properties": {}
}
```

`tableAliases` is optional, so older publishers remain compatible.
Each alias target must be a direct key in `tables`; aliases cannot target another alias.
An alias that equals a canonical key is valid only when it targets itself, which makes the entry a no-op.
The service rejects empty names, dangling targets, chains, cycles, and aliases that contradict canonical keys before cache admission.
Alias strings and lookup entries count toward the catalog memory limit.

The in-memory registry has two bounds:

- a publication TTL expires entries after their catalog was published; and
- least-recently-used eviction caps both the number of entries and their estimated resident bytes.

The generated scale fixture verifies the HTTP publication path, completion, pagination, and validation with 4,096 canonical tables, 25 fields per table, and 120,000 event properties in one property namespace.
The table fields are columns, not part of the property count.
This profile fits the `64 MiB` request limit and the default `8 GiB` shared cache budget, but it is not an unlimited count guarantee.
Longer names and richer metadata increase both serialized and resident sizes.

Warm autocomplete and validation reuse a published catalog without synchronous metadata requests.
A missing or incompatible catalog triggers synchronous catalog construction and publication in Django before the service retry.

## API direction

The initial internal API supports:

- publishing and deleting a catalog for one team and user;
- contextual autocomplete with at most 25 results and cursor pagination; and
- syntax and catalog-backed semantic validation.

Responses return the catalog revision used for computation. Callers can discard results produced from a stale
revision.

HogQL translation is the next service capability. Its stable response should contain parameterized ClickHouse SQL,
bound values, referenced resources, output schema, warnings, and catalog revisions. The internal parser AST is not an
API contract.

## Deployment and rollout

The production container builds a static binary with Go 1.27.1 and runs as a non-root user. A non-loopback listener
fails startup unless dedicated signing keys are configured.

Local and debug environments may use the service directly. Production integration remains behind a server-side
feature flag and should progress through shadow comparison before serving editor results.
The Go consumer accepts alias metadata, and Django always publishes resolver-confirmed warehouse aliases.
Django refreshes cached catalogs with numeric or `legacy-v1` revisions before it uses their responses.
Each request attempts at most one publication and one post-publication retry; marker and lease paths add only bounded Go rechecks.
The retry must return an alias-capable revision, but a concurrent publication for the same team and user can supersede the requested revision.
If publication fails or a catalog cannot represent the resolver result, Django uses the Python autocomplete or validation path.
Malformed HTTP payloads, incompatible revisions after refresh, and malformed autocomplete or validation mappings also use the Python path.
Malformed service responses produce a sanitized Error Tracking event without the SQL text, response body, user context, or original exception.

Full-query HogQL autocomplete and metadata can use the language service when `sourceQuery` is absent or is a `HogQLQuery`.
Only the current editor SQL is sent, together with the cursor position for autocomplete.
The editor can retain an older or incomplete `sourceQuery` while the current SQL changes; full-query metadata does not use that source text.
For example, metadata for `SELECT distinct_id FROM events` can use Go even if `sourceQuery.query` is `SELECT event FROM events WHERE` and `indexUsage` is true.
Both operations continue to use Python when `connectionId`, `globals`, `filters`, or `modifiers` is not null.
Metadata also uses Python when `variables` is not null or `debug` is true.
Expression languages and non-`HogQLQuery` source contexts remain on Python because they can require surrounding query resolution.
Service failures preserve the original request, including its source context, for Python fallback.

Go metadata returns diagnostics and logical table names, not the full Python compiler metadata.
`indexUsage: true` does not force Python fallback or enable index analysis in Go.
Go responses leave `index_usage`, `isUsingIndices`, and `ch_table_names` unset, and return an empty `notices` list.
Python-only heuristic warnings, type notices, and actionable index warnings are not added to a successful Go response.
Index analysis and compiler metadata parity remain separate follow-up work; this routing change does not add a second Python validation pass.

For authenticated requests that have the service configured and the feature flag enabled, the Prometheus counter `hogql_editor_assist_responses_total` counts the backend that produced the final successful editor response.
Its bounded attributes are the operation, backend, and routing reason.
The operation is `autocomplete` or `metadata`, the backend is `language_service` or `python`, and the reason is `served`, `ineligible`, `service_error`, or `invalid_response`.
The denominator includes enabled requests that are ineligible for the Go service and use Python.
It excludes disabled requests, requests without a user, and requests that fail before either backend constructs a response.
The existing Django Prometheus scrape exports the counter for Grafana without another setting.
It aggregates enabled teams and users because it has no tenant labels.
Use this query to compare response rates by backend:

```promql
sum by (operation, backend) (rate(hogql_editor_assist_responses_total[5m]))
```

Use this query for the Python share of successful enabled responses in each operation:

```promql
(
  sum by (operation) (rate(hogql_editor_assist_responses_total{backend="python"}[5m]))
  or on (operation)
  0 * sum by (operation) (rate(hogql_editor_assist_responses_total[5m]))
)
/
sum by (operation) (rate(hogql_editor_assist_responses_total[5m]))
```

An absent series can mean no observations or a missing scrape.
The share is undefined when an operation has no successful enabled responses in the selected interval.

After a missing or legacy catalog response, Django coordinates publication in Redis by language-service target, catalog contract, team, and user.
A publisher holds a 10-second token-owned lease while it rechecks Go, builds the permission-filtered catalog, and publishes it.
Contenders wait for the lease for at most 250 milliseconds, then recheck Go and use the Python path if the catalog is still unavailable.
Redis socket operations and Go requests have their own bounds; the 250-millisecond contention budget is not a total refresh deadline.
A five-second success marker lets a request recheck Go before acquiring a newly released lease.
The marker is advisory: a missing or legacy Go response overrides it, and neither schemas nor authorization results are stored in Redis.
Redis outages use the existing direct publication path.
If catalog construction outlives the lease, a second publisher can duplicate the Go catalog build and publication.

### Autocomplete response timings

Autocomplete responses include timings for the Django editor-assist handler, including requests that fall back to Python.
The existing `language_service_http` value measures only the final successful service request's HTTP duration.
The existing `language_service_go` value measures the Go computation reported by that response.
Neither value includes earlier catalog misses, catalog construction, publication, or Redis coordination.

The `./editor_assist` timing measures the whole autocomplete handler.
Nested stages use the following suffixes:

| Stage                                         | Work measured                                                                  |
| --------------------------------------------- | ------------------------------------------------------------------------------ |
| `routing`                                     | Feature-flag evaluation and eligibility checks                                 |
| `language_service_initial`                    | Initial service call, including a catalog miss or failure                      |
| `catalog_coordination`                        | Full catalog recovery, including its nested stages                             |
| `catalog_coordination/redis_marker_lookup`    | Redis client setup and success-marker lookup                                   |
| `catalog_coordination/redis_lock_acquire`     | Lease acquisition, including contention waiting                                |
| `catalog_coordination/language_service_check` | Accumulated service rechecks and retries                                       |
| `catalog_coordination/catalog_schema`         | Permission-filtered database schema construction                               |
| `catalog_coordination/catalog_build`          | Catalog payload construction, including properties and aliases                 |
| `catalog_coordination/catalog_publish`        | Publication, including signing, payload serialization, and the service request |
| `catalog_coordination/redis_marker_write`     | Success-marker write                                                           |
| `catalog_coordination/redis_lock_release`     | Lease release                                                                  |
| `response_mapping`                            | Conversion of the service response into autocomplete suggestions               |
| `fallback_error_tracking`                     | Sanitized error reporting before Python fallback                               |
| `fallback_database`                           | Database preparation for Python autocomplete                                   |
| `fallback_python_autocomplete`                | Python autocomplete computation                                                |

Timings use seconds and fixed stage names, without SQL, table names, or user identifiers.
Only attempted stages appear; a failed stage retains its duration when the request recovers through Python.
Repeated stages accumulate their durations within that request.
Parent timings include their children, so do not sum every entry to calculate total latency.
The final HTTP/Go timings and Python parser timings also overlap the handler stages.

The handler total excludes request queuing, authentication, API request preparation, final API serialization, middleware, and browser/network latency.
If the handler total is small but the browser request remains slow, inspect the enclosing query API traces and browser network timings.
Metadata responses do not expose a timing list; this change does not extend their response schema.

The initial rollout keeps ClickHouse execution in Django:

```text
Django -> language service translation -> Django -> ClickHouse
```

Measurements must separate catalog lookup, parsing, translation, network transit, ClickHouse duration, result
decoding, and serialization. A combined translation and execution path is justified only if the extra service hop
prevents the overhead target.

## Local playground

For manual development testing, the separate [local playground](hogql-language-service-demo.md) embeds the shared HTTP handlers with an isolated synthetic catalog and a browser editor.
It is excluded from the production binary and container image.
Its guide records catalog approximations, unsupported workflows, and follow-up checks.

## Non-goals

- Reimplementing PostHog membership or permission resolution in Go.
- Exposing the language service directly to browsers.
- Treating feature flags as an authorization boundary.
- Moving ClickHouse execution before latency measurements justify it.
- Making the parser's internal AST a compatibility contract.
