---
name: authenticating-to-clickhouse
description: Authenticate a new or changed service to ClickHouse with the rotating ch-podauth ServiceAccount token instead of a static password. Use when adding a service, sidecar, or container that reads or writes ClickHouse, adding a new ClickHouseUser, or hand-building a ClickHouse pool or client for a custom timeout or setting. Covers the token-aware default path (sync_execute, get_client), the rule that a custom pool must pass credential_provider or it silently stays on the static password, wiring the username so the user does not fall back to the default user, and the deploy-side companion in the charts repo. Not for converting an already-deployed user off a static password.
---

# Authenticating to ClickHouse

A service authenticates to ClickHouse with a short-lived ServiceAccount token, validated by the ch-podauth bridge, not a static password. The token rotates, so the client reads it on each use. Read `posthog/clickhouse/client/AGENTS.md` for the full recipe and the traps. This skill is the entry point.

Use it when adding a new service or ClickHouse user, or when building or changing a ClickHouse pool or client by hand. Converting an already-deployed user off a static password is a ClickHouse-team operation and is out of scope.

## Do

- Use the token-aware default paths: `sync_execute(..., ch_user=...)` for pooled queries, or the async `get_client` in `posthog/temporal/common/clickhouse.py` for HTTP. Both read the token on each use.
- Choose the user shape: deployment-default (the pod's default user is the service) or a new `ClickHouseUser` enum member. Wire the username env, or the user silently authenticates as the default user.
- Wire the deploy side in the charts repo. The `connect-app-to-clickhouse` skill mounts the token and sets `CLICKHOUSE_<USER>_PASSWORD_FILE`.

## Do not

- Pass your own `sync_client` to `sync_execute`, or build a pool or client by hand, without keeping it token-aware. A native pool must carry `credential_provider`; an HTTP or one-shot client resolves the token per call instead. A pool that skips this silently stays on the static password. `posthog/clickhouse/client/AGENTS.md` has both shapes.
- Read the credential once at startup, in any language. The token rotates, so read the token file on each connection or request.
