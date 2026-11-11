# ClickHouse client authentication

How code authenticates to ClickHouse.
For migrations, see `posthog/clickhouse/migrations/AGENTS.md`.

A service authenticates to ClickHouse with a short-lived Kubernetes ServiceAccount token.
The on-node ch-podauth LDAP bridge validates the token.
The token file rotates on a short TTL.
The client reads the file on each use and does not cache the value.

## The default path is already token-aware

`sync_execute(..., ch_user=...)` reads the token on each use.
It routes through `get_client_from_pool`, which uses the token-aware `get_pool` for native connections and `get_http_kwargs` for HTTP.
The async temporal client `get_client` in `posthog/temporal/common/clickhouse.py` is token-aware too, because `_request_headers` calls `read_password` on each request.
Use these paths and token auth is automatic.

`get_cluster` in `posthog/clickhouse/cluster.py` is token-aware for the user that its `ch_user` argument resolves to, which is the pod's `CLICKHOUSE_USER` unless you set it: the per-host pools carry a credential provider that re-stamps the live token on each checkout.
Its bootstrap discovery client is long-lived, so each discovery attempt stamps the live token onto it first, including the discovery that `sibling()` runs hours into a job.
A per-host task can hold one checkout for hours, for example a mutation wait.
When the cluster has a retry policy, each attempt of a token-backed task stamps the live token, and the policy also retries a rejected login.
Pass `ch_user` to connect as a dedicated user, the way `get_migrations_cluster` does, because discovery and the pools then both use that user.
A caller that connects as a different user through `connection_overrides` owns its own credential, and its discovery still runs as the pod's `CLICKHOUSE_USER`.
The part_breaker Dagster resource does this: it sets `credential_provider` itself when its user is file-backed, the way `get_pool` does.

`default_client()` without `user` and `password` reads the token for the pod's `CLICKHOUSE_USER` when it builds the client.
It is a one-shot client: close it after one short task, because a retained client that reconnects after the token expires is rejected.

Token-awareness is lost when you pass any other client as `sync_client` to `sync_execute`, or build your own pool or client.

## A custom pool or client must stay token-aware

`credential_provider` is a native-pool mechanism. An HTTP or one-shot client does not use it.

Build a custom native pool for a timeout or a setting only by replicating the file-backed branch of `get_pool`.
A pool that skips this branch stays on the static password with no error.
Resolve the credentials with `get_clickhouse_creds`.
When `is_file_backed_user` is true, pop the static `password` and pass `credential_provider=creds.read_password` to `make_ch_pool`.
`read_password` reads the token file on each call.
It falls back to the static password when the file is unreadable or empty.
For a user that keeps a static password, it also falls back when the token has expired or is about to expire.
`RefreshingChPool` re-stamps the live token on each checkout, so one pool survives a rotation.
The canonical native implementation is `get_pool`.

An HTTP or one-shot client is rebuilt on each call, so it needs no credential provider.
Resolve the token once with `creds.read_password()` and pass it as the password, the way `get_http_kwargs` does.
A client that is retained and reconnects is not one-shot: a token baked into it expires with no recovery, because `read_password`'s expired-token fallback only fires when it is called again.
Stamp `read_password()` onto `client.connection.password` before each use, the way the `get_cluster` bootstrap does, or use a refreshing pool.
A refreshing pool stamps only at checkout, so a client that one checkout holds across a reconnect needs the same stamp.

## Wire the username, or the user falls back to the pod's `CLICKHOUSE_USER`

A dedicated user registers only when both its username env `CLICKHOUSE_<USER>_USER` and a secret are set.
The secret is `CLICKHOUSE_<USER>_PASSWORD` or `CLICKHOUSE_<USER>_PASSWORD_FILE`.
If the username env is missing, `get_clickhouse_creds` returns the credentials of the pod's `CLICKHOUSE_USER`.
The query then runs as that user with no error.
On many pods, including every Django app, `CLICKHOUSE_USER` is the literal `default` user.
A new `ClickHouseUser` member needs its username wired, not only its token file.
`get_clickhouse_creds` decides the missing-credential behavior per user, and some users raise instead of falling back.

## Deployment-default or enum user

Deployment-default: the pod's `CLICKHOUSE_USER` is the service's own user.
Set `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD_FILE`.
`ClickHouseUser.DEFAULT` then resolves to that user and reads its token.
Enum user: add a `ClickHouseUser` member and wire its `CLICKHOUSE_<USER>_USER` and `CLICKHOUSE_<USER>_PASSWORD_FILE`.
A token-first user needs no static password.
The static fallback resolves to an empty string when none is set, so the token is the only working credential.

## Other languages

A non-Python service has no shared helper.
The rule is the same in any language: read the token file on each connection or request.
A client that reads the password once at startup breaks after the first token rotation.

## Deploy side

The token mount and the `CLICKHOUSE_<USER>_PASSWORD_FILE` env are wired in the charts repo.
See its `connect-app-to-clickhouse` skill and `docs/claude/clickhouse-connections.md` when you wire the deployment.
