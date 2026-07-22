# Runtime

Cross-process runtime services shared by the agent node services: event bus, log sink, per-leaf encryption, the team API-key resolver, and the MCP connection store that mints shared-credential bearers.

## invariants

- connection-owner-isolation
- connection-bearer-single-reader
- team-api-key-isolation
- django-fernet-interop
- gateway-wire-single-source
- gateway-cost-provenance
- direct-http-capability-divide

## works when

- typechecks
- boundary "connection-owner-isolation" at PgMcpConnectionStore
- passes test "cannot return owner B"
- boundary "connection-bearer-single-reader" at PgMcpConnectionStore via guard "reads of sensitive_configuration are confined"
- boundary "team-api-key-isolation" at PgTeamApiKeyResolver
- passes test "returns only its own api_token"
- boundary "django-fernet-interop" at EncryptedFields
- passes test "urlsafe regression"
- boundary "gateway-wire-single-source" at extractGatewayRequestId
- passes test "request id single-sourcing"
- boundary "gateway-cost-provenance" at assertGatewayProvenance
- passes test "cost provenance guard"
- boundary "direct-http-capability-divide" at DirectHttpClient via guard "does NOT accept a proxyUrl in its options"

## why

connection-owner-isolation: a shared MCP connection's stored bearer belongs to the spec author (`agent_revision.created_by_id`). resolve scopes the lookup to (installation, team, owner) so no authoring path can hand a credential to a non-owner — enforced at the runtime chokepoint every session crosses, not at spec-write (which is routable-around). The oracle runs the real exported SQL against real Postgres with two owners, because a fake-pool test only proves the param is passed, not that the predicate filters.
connection-bearer-single-reader: the owner check is complete only if the store is the sole reader of the credential column, so the oracle confirms no other module reads it and the chokepoint can't be bypassed.
team-api-key-isolation: the resolver's `phc_` lookup is the team's bearer to PostHog services; dropping or inverting the `WHERE id = $1` predicate mints a sibling team's token (cross-tenant billing/attribution) while every fake-pool unit test stays green. The oracle runs the real exported `SELECT_TEAM_API_TOKEN` against real Postgres with two teams.
django-fernet-interop: the runner decrypts what Django's `EncryptedTextField` wrote, so key derivation must match Django's urlsafe-base64 form exactly — standard base64 differs only for salt keys whose encoding contains `+`/`/`, and that divergence fails silently (every decrypt of Django ciphertext breaks for that key, with nothing wrong at rest). The oracle decrypts real Django-written ciphertext, including a key that exercises the urlsafe divergence.
gateway-wire-single-source: the runner↔ai-gateway contract (auth header shape, the response header carrying the gateway's settlement id, the usage-lookup path built from that id) is declared once in `gateway-wire.ts` and imported by dispatch, catalog, and the settled-cost lookup — the same symbol on both sides, so keying settlement by the wrong id or drifting the header shape is unrepresentable rather than remembered. The oracle drives a stubbed gateway end-to-end and asserts the id dispatch received is the id the cost lookup keys on.
gateway-cost-provenance: cost figures on analytics generation events must come from gateway-settled usage, never local estimates — `GatewaySettledCost` carries a literal `source: 'gateway'` and `assertGatewayProvenance` backstops it at `buildAnalyticsProperties`, the single funnel both sinks route every event through, dropping-and-logging a forged or unsourced cost instead of emitting it.
direct-http-capability-divide: two HTTP clients exist deliberately separate. `HttpClient` is proxy-bound (smokescreen in prod) and is the only client agent-influenced code can reach — `ToolContext.http` is typed `HttpFetcher` and every non-test construction site hands it an `HttpClient`. `DirectHttpClient` carries no proxy dispatcher at all and is reserved for cluster-internal calls the platform makes to itself (`HttpGatewayClient`, the PostHog introspector); it must never be threaded onto `ToolContext` or a runner `WorkerDeps` — a NO_PROXY-style hostname allowlist would defeat the divide (an `@posthog/http-request` call against an in-cluster `*.svc.cluster.local` hostname would match a suffix rule and bypass smokescreen entirely), so the class identity itself is the capability, not a runtime check. Bare global `fetch` is lint-banned across `services/agent-*/src` (`no-restricted-globals` in `.oxlintrc.json`) because Node's built-in `fetch` ignores `HTTP_PROXY`/`HTTPS_PROXY` and would silently skip both clients. The oracle pins the half of the divide that's actually executable: `DirectHttpClient`'s constructor has no `proxyUrl` option (a compile-time `@ts-expect-error` on the options type), so there is no escape hatch to wire a proxy onto the internal-only client after the fact.
