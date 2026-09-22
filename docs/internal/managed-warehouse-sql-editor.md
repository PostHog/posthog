# Managed warehouse connections in the SQL editor

The `data-warehouse-scene` feature flag gates user access to managed warehouse provisioning. It does not select a SQL-editor authentication mode. Once a provision, onboarding, or generation-fenced recovery lifecycle action runs, a genuinely missing managed source is created unconditionally as a secretless `duckgres_service` source and presented as `PostHog (Managed warehouse)`.

A `duckgres_service` row persists no host, username, password, or credential ID. It persists only the non-secret lifecycle generation that created it. Dynamic raw queries use the native Duckgres pgwire adapter. At physical connection acquisition, PostHog mints a short-lived organization-root-shaped service credential for a principal containing the project ID and stable PostHog user ID. Email addresses are never used. Schema discovery uses a distinct project-scoped system principal, so background work never impersonates an interactive user. The connection must include `sslmode=require`, and there is no stored-root fallback.

Existing live sources keep their stored authentication mode unless an actual warehouse lifecycle action requires replacement. A live dynamic source remains dynamic, a configured `project_reader` retains its stored project credential, and a static organization-login source retains its stored root credential and external-source access controls. The database chooser prefers a dynamic source, then a ready `project_reader`; when neither exists, it exposes the canonical valid legacy source as an ordinary external connection. Merely changing a product feature flag does not create, convert, or hide a source.

PostHog application-encrypts credentials in shared Redis. The cache key is a hash of the organization, principal, and lifecycle generation, and the entry expires one minute before the credential. A per-key Redis lock lets query-django and Celery workers share one mint without making unrelated principals wait. Refresh always mints an independent credential and never rotates a cached credential ID. A rapid deprovision and reprovision therefore cannot reuse a credential from the old generation.

Redis is the only credential cache. When Redis cannot be read, locked, or written, the request mints directly and does not retain a process-local copy. A lock wait is bounded to four seconds. After that, the request checks Redis once more and mints directly if the owner did not publish a credential. A valid cached credential can bridge a temporary control-plane outage until its refresh margin. After that, mint failure fails closed. The connection must include `sslmode=require`, and there is no stored-root fallback.

The credential cache uses a dedicated Redis client with no command retries. `MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_CONNECT_TIMEOUT_SECONDS` and `MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_READ_TIMEOUT_SECONDS` both default to 0.5 seconds. Timeout and retry query parameters in `REDIS_URL` are ignored for this client, while authentication, database, TLS, and other Redis options remain intact. These settings do not change the shared Redis client's longer timeout for blocking operations.

An organization-scoped generation fence orders source work around remote provision and deprovision calls. A stale provision completion cannot revive a source after a later deprovision, and an old cleanup retry cannot delete a genuinely reprovisioned source. If cleanup failed before a genuine reprovision, static and `project_reader` sources from the deleted warehouse generation are tombstoned with their tables before setup creates dynamic authentication. An existing dynamic source instead advances its lifecycle generation. Credentials therefore cannot cross warehouse generations.

Reconciliation treats dynamic, project-reader, and static sources as independent catalogs and introspects each with its own credential mode. A failure in one source does not block the others. Dynamic discovery requires TLS and uses its system principal. Reconciliation runs when warehouse status is read, coalesced to once a minute, and in a twice-hourly periodic sweep. For an active generation with a missing source, reconciliation creates dynamic authentication without reading `DuckgresServer`.

The native adapter sends one PostgreSQL-compatible statement unchanged, supports asynchronous cancellation, applies the existing connection deadline and statement timeout, and rejects results above 50,000 rows. Non-raw project-reader and static-source queries continue through their existing PostgreSQL/HogQL path; the PostgreSQL adapter is unchanged.

Deprovision captures the active generation before the control-plane request and deactivates only that generation. A direct 404 is authoritative absence. If the request times out or returns 409, PostHog reads warehouse status. It converges local cleanup only when the warehouse is `deleting`, `deleted`, or absent. A ready warehouse remains active.

## Deployment and rollback

1. Keep `MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED=true` in the current web, admin, and Celery deployments throughout the rolling code deployment. Old workers use that setting, while new workers create dynamic sources unconditionally, so both versions agree.
2. Deploy this code to every web, admin, and Celery process. New producers always emit generation-aware v2 cleanup and source-recovery tasks.
3. Drain queued, reserved, scheduled, and retry source-recovery work after no old process remains.
4. Remove `MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED` from the charts in a separate deployment. New code no longer reads it.

Rolling back to old code requires restoring or retaining `MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED=true` first. Removing the charts setting before the old fleet and its queues are drained would make old workers drop recovery tasks.

The legacy cleanup task keeps its one-argument wire signature so new workers can consume messages queued before this deployment. Its handler takes the organization lock, cleans the current inactive generation, does nothing for an active lifecycle, and uses unconditional legacy behavior only when no lifecycle row exists. New producers emit only versioned generation-aware cleanup tasks. Cleanup is independent of credential mode and generation-fenced.

Source setup, query authentication, schema discovery, and generation-fenced deprovision cleanup do not read `DuckgresServer`. The model remains for persistence of the one-time provision response, legacy consumers, and rotating root passwords on grandfathered static sources.

The historical query-status label prefix `managed-warehouse-sql-editor:` remains only as an in-flight wire identifier. It is not a feature flag. Renaming or removing it requires a later dual-read rollout and a drain of query statuses produced by old workers.

## Failure recovery

If source setup fails after successful provision or onboarding, the versioned retry task uses the original team, organization, and generation. It is safe to retry and creates dynamic authentication when the source is still missing. If the warehouse was deprovisioned or reprovisioned, the generation check turns a stale task into a no-op.

If deprovision reports that the control plane accepted deletion but local SQL connection state could not be updated, retry deprovision. PostHog checks authoritative status before changing local state. If source cleanup fails after local deactivation, the versioned cleanup task retries with the exact inactive generation.

If Redis is unavailable, SQL editor queries and managed warehouse schema discovery continue by minting one credential per request. Restore Redis to resume cross-worker reuse. There is no process-local or Postgres credential cache to clear during recovery. Use `posthog_managed_warehouse_service_credential_cache_events_total` to compare cache hits, misses, invalid payloads, Redis errors, lock timeouts, store failures, and direct fallbacks. Its `outcome` label has no tenant or credential identifiers.
