# pgapi — Postgres telemetry API and MCP server

`rust/pgapi` serves the telemetry collected by `rust/pgcollector` (see
[pgcollector.md](pgcollector.md)) as a read-only REST API, an MCP server and a
small embedded UI. Crate-level details live in
[`rust/pgapi/README.md`](../../rust/pgapi/README.md); this page is the service
contract.

## Surfaces

| path                              | what                                                                                                                                                                            | auth              |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `/api/v1/*`                       | JSON API: servers, overview, queries, query tags, activity, locks, sessions, tables, indexes, vacuum, events, logs, system, schema, settings, collector health, guarded raw SQL | identity required |
| `/mcp`                            | MCP streamable HTTP, 19 read-only tools over the same query layer                                                                                                               | identity required |
| `/`                               | embedded UI over `/api/v1`                                                                                                                                                      | identity required |
| `/healthz`, `/readyz`, `/metrics` | probes and Prometheus                                                                                                                                                           | none              |

## Query tags

Queries are labelled by the tags their clients put in SQL comments, not only by
their text. `GET /servers/{id}/tags?key=<tag key>` (MCP `query_tags`) gives load
per code path; `GET /servers/{id}/queries?tags=key=value` filters the
`pg_stat_statements` list to queries seen with a tag; query detail lists the
`callers` seen while the query ran. The tag format and key vocabulary are in
[`rust/pgcollector/docs/query-tags.md`](../../rust/pgcollector/docs/query-tags.md).

## Charts

The UI draws its charts from bucketed endpoints. `GET /servers/{id}/load?bucket=1m`
gives average active sessions per bucket by wait event type, summed over instances,
with the host core count; it is the Overview page's database load chart. Every ranged
endpoint accepts `since` or absolute `from`/`to`, which is how a range dragged on a
chart is fetched. `GET /servers/{id}/events?exclude=pgss_dealloc,log_cancel,log_lock%`
leaves out routine kinds before the limit, so event markers show the rare kinds.

## Lock waits

`GET /servers/{id}/locks` (MCP `lock_waits`) answers "who waited for whom" over a
range from the 10 s blocking-graph samples: sessions waiting per bucket by lock type,
(blocker statement, waiter statement) pairs with waiter-seconds and how often the
blocker sat idle in transaction, blocking episodes (consecutive samples of one waiter
and blocker pair) with the blocker's transaction age, and deadlocks from the log.
`GET /servers/{id}/sessions/{pid}?instance=writer&from=&to=&backend_start=` returns one
backend's long-session samples, which the Locks page uses to show what a blocker ran before
it went idle. `backend_start` tells a reused pid apart; without it the backend sampled
nearest to `at` is returned.

## Identity and authorization

The app runs no OAuth flow. Identity is established at the edge and read from
headers, each source bound to the ingress that sets it:

1. `Tailscale-User-Login` — only when `PGAPI_TRUST_TAILSCALE=1` **and** the
   request `Host` is a tailnet host (`PGAPI_TAILSCALE_HOSTS`, default
   `*.ts.net`), so a forged header on the Cognito host is ignored. The deploy
   must pair this with a NetworkPolicy admitting only the Tailscale operator's
   proxy pods.
2. `x-amzn-oidc-data` — ALB + Cognito JWT, verified ES256 against the regional
   ALB key endpoint; issuer must be a Cognito pool in `PGAPI_ALB_REGION`, the
   token must be minted for `PGAPI_ALB_CLIENT_ID` and signed by the ALB in
   `PGAPI_ALB_ARN` (JOSE `signer`), and `email_verified` must be true.
3. `X-Auth-Request-Email` — in-cluster auth gateway, only with
   `PGAPI_TRUST_GATEWAY=1`.
4. `PGAPI_DEV_USER` with `PGAPI_DEV_MODE=1` — local development only.

Authorization is by email domain (`PGAPI_ALLOWED_DOMAINS`, default
`posthog.com`) or explicit list (`PGAPI_ALLOWED_EMAILS`). There is one role:
everything is read-only. Every request is logged with the caller's email and
identity source.

## Data sensitivity

The stats database holds statement text from every monitored cluster. The
collector redacts string literals before storing log-derived statements, but
table names, query shapes and plan parameters are visible to anyone who can
authenticate. Keep the audience to engineering.

## Raw SQL tool

`GET /api/v1/sql` and the `query_stats_db` MCP tool run a single
`SELECT`/`WITH`/`EXPLAIN` against the stats database inside a read-only
transaction with a 15 s timeout under an 8 MiB serialised-response budget
(rows are streamed and the query cancelled past it), then `DISCARD ALL` the
session. Calls to
side-effecting functions (`pg_sleep`, advisory locks, `set_config`,
`pg_terminate_backend`, stats resets, file/backup functions, `dblink`, …) are
refused up front. The database
user is a read-only role. This is for agents answering questions the fixed
tools do not cover.

## Configuration

Environment variables are documented in `rust/pgapi/src/main.rs` (`--help`).
Deployment values for the golden chart are in `rust/pgapi/values.example.yaml`.
