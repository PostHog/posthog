# Managed warehouse connections in the SQL editor

The `managed-warehouse-sql-editor` feature flag controls which managed warehouse connection appears in the database chooser. With the flag enabled, PostHog prefers a secretless `duckgres_service` source and presents it as `PostHog (Managed warehouse)`. An existing configured `project_reader` source remains a temporary built-in compatibility path when no dynamic source exists. With the flag disabled, a grandfathered static organization-login source remains an ordinary external Duckgres connection.

`MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED` is a deployment-wide operational gate that defaults to false. While it is false, provision and project onboarding preserve the existing static `org_root` source behavior and do not create dynamic sources. While it is true, new source setup creates `duckgres_service` sources. These rows persist no host, username, password, or credential ID. They persist only the non-secret lifecycle generation that created them.

Existing active `project_reader` and static organization-login sources remain byte-for-byte unchanged. Turning the operational gate off leaves a same-generation dynamic source byte-for-byte unchanged and never copies the stored root secret into that row. After a failed cleanup, a genuine reprovision keeps an existing dynamic source but advances its lifecycle marker and makes readers from the old generation unavailable. Without a dynamic source, gate-off reprovision makes stale readers unavailable before creating the static source. Dynamic-mode reconciliation never creates or revives sources. While the operational gate is off, reconciliation may complete generation-fenced static source setup after a successful provision, but it does not revive an unfenced legacy tombstone.

Dynamic raw queries use the native Duckgres pgwire adapter. At physical connection acquisition, PostHog mints a short-lived organization-root-shaped service credential for a principal containing the project ID and stable PostHog user ID. Email addresses are never used. Schema discovery uses a distinct project-scoped system principal, so background work never impersonates an interactive user.

PostHog application-encrypts credentials in shared Redis. The cache key is a hash of the organization, principal, and lifecycle generation, and the entry expires one minute before the credential. A per-key Redis lock lets query-django and Celery workers share one mint without making unrelated principals wait. Refresh always mints an independent credential and never rotates a cached credential ID. A rapid deprovision and reprovision therefore cannot reuse a credential from the old generation.

Redis is the only credential cache. When Redis cannot be read, locked, or written, the request mints directly and does not retain a process-local copy. A lock wait is bounded to four seconds. After that, the request checks Redis once more and mints directly if the owner did not publish a credential. A valid cached credential can bridge a temporary control-plane outage until its refresh margin. After that, mint failure fails closed. The connection must include `sslmode=require`, and there is no stored-root fallback.

The credential cache uses a dedicated Redis client with no command retries. `MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_CONNECT_TIMEOUT_SECONDS` and `MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_READ_TIMEOUT_SECONDS` both default to 0.5 seconds. Timeout and retry query parameters in `REDIS_URL` are ignored for this client, while authentication, database, TLS, and other Redis options remain intact. These settings do not change the shared Redis client's longer timeout for blocking operations.

Existing project readers retain their stored, project-scoped credential and native-adapter behavior. Existing static organization-login sources retain the PostgreSQL adapter and external-source access controls. Saved connection IDs continue to resolve according to the source's own credential mode even when that mode is not the chooser's preferred entry.

The native adapter sends one PostgreSQL-compatible statement unchanged, supports asynchronous cancellation, applies the existing connection deadline and statement timeout, and rejects results above 50,000 rows. Non-raw project-reader and static-source queries continue through their existing PostgreSQL/HogQL path; the PostgreSQL adapter is unchanged.

Reconciliation treats dynamic, project-reader, and static sources as independent catalogs and introspects each with its own credential mode. A failure in one source does not block the others. Dynamic discovery requires TLS and uses its system principal. Reconciliation runs when warehouse status is read, coalesced to once a minute, and in a twice-hourly periodic sweep. Dropped and recreated tables revive their existing catalog entries.

An organization-scoped generation fence orders local source lifecycle work around remote provision and deprovision calls. Successful explicit provision or onboarding owns source creation. A stale provision completion cannot revive a source after a later deprovision, and an old cleanup retry cannot delete a genuinely reprovisioned source. Reconciliation also requires the same active generation before and after remote schema discovery.

Deprovision captures the active generation before the control-plane request and deactivates only that generation. A direct 404 is authoritative absence. If the request times out or returns 409, PostHog reads warehouse status. It converges local cleanup only when the warehouse is `deleting`, `deleted`, or absent. A ready warehouse remains active. Failed local dynamic source setup schedules a generation-fenced v2 retry; retries from an inactive or newer generation do nothing. With the operational gate off, periodic reconciliation repairs failed static source setup against the active generation.

## Deployment and rollback

1. Deploy this code to every web and Celery worker with `MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED=false`.
2. Confirm provision and onboarding still create or maintain static `org_root` sources.
3. Drain old web and Celery workers. Also drain queued, reserved, scheduled, and retry messages for `products.data_warehouse.backend.tasks.soft_delete_managed_warehouse_sources`.
4. Enable `MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED=true` on web and Celery together. Only then do producers emit the generation-aware v2 cleanup and source-recovery tasks.

The legacy cleanup task keeps its one-argument wire signature so a new worker can consume messages queued by an old worker. While the gate is off, new producers emit only that legacy task. The handler takes the organization lock: it cleans the current inactive generation, does nothing for an active lifecycle, and uses unconditional legacy behavior only when no lifecycle row exists. While the gate is on, the legacy handler does nothing and producers emit only versioned generation-aware tasks. This prevents either worker version from receiving a payload shape it cannot execute during the drain.

Before enablement, rollback is a normal code rollback. After enablement, disable the gate to stop creating dynamic sources, but keep the new binaries running so existing dynamic sources remain queryable. Do not deploy old binaries until no live `duckgres_service` sources remain or an explicit conversion process has replaced them with static sources.

Dynamic source creation while the gate is enabled, query authentication, schema discovery, and generation-fenced deprovision cleanup do not read `DuckgresServer`. The model remains for gate-off static source creation, persistence of the one-time provision response, and rotating root passwords on grandfathered static sources.

## Failure recovery

If source setup fails after successful provision or onboarding, the versioned retry task uses the original team, organization, and generation. It is safe to retry. If the warehouse was deprovisioned or reprovisioned, the generation check turns the task into a no-op.

If deprovision reports that the control plane accepted deletion but local SQL connection state could not be updated, retry deprovision. PostHog checks authoritative status before changing local state. If source cleanup fails after local deactivation, the versioned cleanup task retries with the exact inactive generation.

If Redis is unavailable, SQL editor queries and managed warehouse schema discovery continue by minting one credential per request. Restore Redis to resume cross-worker reuse. There is no process-local or Postgres credential cache to clear during recovery. Use `posthog_managed_warehouse_service_credential_cache_events_total` to compare cache hits, misses, invalid payloads, Redis errors, lock timeouts, store failures, and direct fallbacks. Its `outcome` label has no tenant or credential identifiers.
