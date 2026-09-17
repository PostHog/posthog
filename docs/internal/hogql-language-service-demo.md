# Local HogQL playground

The playground embeds the real Go language service's HTTP handlers in the demo process.
It loads a synthetic catalog and serves a small browser editor, without Django, ClickHouse, project data, or credentials.
It does not execute queries.

## Run

From the repository root:

```bash
.codex/with-flox env GOTOOLCHAIN=auto go -C services/hogql-language-service run ./cmd/demo
```

Open <http://127.0.0.1:8092>.
Use `-port 8093` after `./cmd/demo` if the default port is occupied.
For port forwarding, bind the demo page to all interfaces:

```bash
.codex/with-flox env GOTOOLCHAIN=auto go -C services/hogql-language-service run ./cmd/demo -host 0.0.0.0
```

Forward port `8092` and open the forwarded URL.
This mode accepts the forwarded hostname and HTTP or HTTPS origins matching that hostname.
The demo has no authentication; use your development environment's private forwarding controls.
Only the demo page listens on a port; the embedded service has no separate listener.
Go may download the module's required toolchain on the first run.
Agents must request elevated execution when starting the demo because it opens a local HTTP listener.

The demo and `cmd/server` share `internal/httpapi`, including request decoding, completion, validation, response encoding, and rate limiting.
The demo seeds a private in-memory catalog for synthetic team 1 / user 1 and dispatches requests directly to those handlers.
It does not spawn subprocesses, build another binary, poll readiness, or use an HTTP client.
Demo settings are explicit and do not read production service environment variables.
It does not connect to or modify an existing development service.
The catalog lives in memory with a 24-hour TTL; restart the demo to refresh it.
Ctrl+C stops the demo server.
The page defaults to `127.0.0.1` and accepts requests for its own host and origin.
Binding to `0.0.0.0` or `::` permits other hostnames for forwarding while still rejecting cross-origin browser requests.

The production Dockerfile builds only `cmd/server` and copies only that binary into its final image.
The demo command, its embedded browser assets, and synthetic catalog are not included in that binary or final image.
Production authentication and environment configuration remain in `cmd/server`.
The demo exposes only fixed-scope completion and validation adapters, not the service's catalog mutation routes.
Do not add the demo to deployment configuration or the production server's routes.

## Manual checks

- Select **Event fields**, click **Complete at cursor**, then click a suggestion to insert it.
- Select **Valid CTE** and click **Validate**. The service should accept the query and list `events` as its underlying table.
- Select **Unknown field** or **Unknown table** to inspect diagnostics and typo suggestions.
- Select **Unicode diagnostic offsets**, validate, and click the diagnostic. It should select `timstamp`, even with the emoji earlier in the query.
- Select **Property pagination** and use **Load more** to retrieve all 35 matching names.
- Select **Quoted identifiers** and insert `billing address` to inspect identifier quoting. The service supplies quoted insertion text; the page does not add quotes.
- Use **CTE completion** and **Subquery completion** to inspect current derived-relation support. Empty suggestions are shown as returned by the service, without a browser fallback.
- Open raw responses to inspect parser errors, diagnostics, pagination cursors, physical table names, and catalog revisions.

Ctrl/Command+Enter validates; Ctrl/Command+Shift+Enter completes.
Ctrl+Space is left available for the operating system's input-source shortcut.
Enable **Analyze as you type** to run both operations after a 300 ms typing pause.
The checkbox is off by default. Enabling it also analyzes the current query; loading an example or inserting a suggestion schedules analysis too.
Turning it off cancels scheduled analysis and in-flight requests. Manual buttons and shortcuts remain available.
Empty queries trigger completion for SELECT and WITH, but not validation.
Unfinished input-method composition does not trigger automatic requests.
Completion requests use UTF-16 offsets, matching the textarea selection API.
Validation requests explicitly select UTF-8 offsets; the page converts those byte ranges to UTF-16 for diagnostic selection.
Raw responses and copied exchanges keep the service's original offsets.
The page shows service time separately from browser round-trip time.
Editing the query clears results and cancels pending requests; moving the cursor clears completion results.

## Share a reproduction

Each result panel has a **Copy request and response** button.
It copies a JSON record of the most recent completed request for that operation, including the original query, completion cursor position and pagination cursor, completion encoding, HTTP status, and full response with catalog revision.
The browser path and corresponding service path are included for replay.
HTTP errors retain their response body, and network errors retain their request and error message.
Canceled requests do not replace the last captured exchange.

Each panel keeps one captured exchange when you edit the query or move the cursor; the next completed request for that operation replaces it.
For pagination, the copied exchange represents the latest page, including the cursor used to request it.
Turn off **Analyze as you type** to keep a reproduction while experimenting further.
The capture is kept only in page memory and is lost on refresh.

If clipboard access is unavailable, including on some HTTP forwarded URLs, the button opens and selects the captured JSON so you can press Ctrl/Command+C.
Paste it with a short description of the expected suggestions to report an autocomplete issue.
The demo does not send feedback anywhere automatically.

## Catalog

`services/hogql-language-service/cmd/demo/catalog.go` defines a hand-maintained subset of the public HogQL schema shapes for `events`, `persons`, `sessions`, and `groups`.
It also defines invented `postgres.demo.orders` and `demo_customers` warehouse tables, event/person/session/group property namespaces, and 35 `demo_property_*` names for pagination.
Only names and types are present; there are no event rows, person records, customer examples, or production schema exports.
The sidebar and `/api/catalog` display the exact catalog published to the service.
To change it, edit `catalog.go` and restart the command.

## Exclusions and follow-up work

These are deliberate boundaries of the demo or service behavior to investigate later.
They are not evidence that a query would succeed or fail in the full PostHog compiler.

| Area                                   | Current boundary and reason                                                                                                                                                                                                                                                       | Follow-up and acceptance check                                                                                                                                                                                                  |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full PostHog catalog parity            | The fixture is a small, static subset so the demo runs without Django. Virtual joins and all product tables are not modeled completely.                                                                                                                                           | Add an optional catalog generator using a synthetic local project. Compare its published schema with Django's catalog for that project and document required services.                                                          |
| Derived-relation completion            | The service resolves CTE and aliased subquery fields through the shared analyzer. The page does not invent missing suggestions.                                                                                                                                                   | Use the examples to check projected fields, aliases, types, and direct property origins. Structured recovery for malformed queries remains separate work.                                                                       |
| Identifier quoting                     | The page uses the service's quoted `insertText`. Completion inside an already quoted identifier is not supported by the textarea adapter.                                                                                                                                         | Add quote-aware token replacement before supporting completion inside existing quotes. Check escaped backticks and mid-token edits.                                                                                             |
| Alias and property semantics           | The service preserves direct property origins through derived fields and visible SELECT aliases. Computed or ambiguous origins do not produce property suggestions.                                                                                                               | Check event/person separation, renamed containers, and aliases in supported clauses. Computed-expression and nested JSON provenance require separate design and tests.                                                          |
| Other HogQL constructs                 | Examples do not establish coverage for unions, scalar `WITH` aliases, CTE column-name lists, recursive CTEs, or every dialect.                                                                                                                                                    | Decide supported constructs explicitly in the analyzer design; add examples and observable regression coverage for each supported construct. Retain the service's exclusion of recursive CTE support unless that scope changes. |
| Query execution and compiler parity    | No database or Python metadata endpoint is called; validation reflects only this Go service.                                                                                                                                                                                      | Add an opt-in comparison mode against a synthetic local Django project if compiler parity testing is needed. Keep execution separate and explicitly enabled.                                                                    |
| Editor integration                     | A textarea keeps the page dependency-free. Optional debounced validation and completion run after edits. Monaco highlighting, squiggles, and completion inside already quoted identifiers are not provided. Insertion replaces an ordinary identifier around the captured cursor. | Add a locally bundled editor adapter when testing editor behavior, with cursor/range tests for quoted names, escaped characters, and mid-token edits.                                                                           |
| Custom catalog editing and permissions | One synthetic team/user catalog is seeded at startup. There is no upload UI, identity picker, catalog refresh button, permission mutation, or JWT workflow.                                                                                                                       | Add isolated synthetic catalog variants for permission/tenant testing; verify catalog revisions and isolation through authenticated endpoints before adding identity controls.                                                  |
| Performance conclusions                | The fixture is small and timings are exploratory. This page is not a load test or latency acceptance gate.                                                                                                                                                                        | Use the existing large-catalog benchmarks and dedicated latency test; add query-shape benchmarks for the shared analyzer as needed.                                                                                             |
| Hosting and production                 | Private development port forwarding is supported with `-host 0.0.0.0`. The demo serves HTTP without authentication or built-in TLS and stays excluded from production.                                                                                                            | Use authenticated development forwarding. Public hosting would need a separate authentication and TLS design; production service endpoints remain outside this demo.                                                            |
| Persistence                            | Query text and results live only in the page; refreshing discards them. This avoids silently storing pasted query text.                                                                                                                                                           | If useful, add explicit local export/import of synthetic examples with a documented file format.                                                                                                                                |

## Verification

```bash
.codex/with-flox env GOTOOLCHAIN=auto go -C services/hogql-language-service test ./cmd/demo
.codex/with-flox env GOTOOLCHAIN=auto go -C services/hogql-language-service vet ./cmd/demo
```

Browser checks must exercise this page against the embedded service, including completion insertion, pagination, Unicode diagnostic selection, stale-response handling, and a narrow desktop window.
