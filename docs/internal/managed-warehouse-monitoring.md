# Managed warehouse monitoring

The **Monitoring** tab in Data ops gives every project in an organization the same operational view of its managed warehouse.
It combines a current fleet snapshot with allowlisted historical metrics from Duckgres.

## Request path and tenant boundary

The browser calls project-scoped PostHog endpoints:

- `GET /api/projects/{team_id}/data_warehouse/managed-warehouse-monitoring/`
- `GET /api/projects/{team_id}/data_warehouse/managed-warehouse-monitoring-timeseries/?metric=...&window=...`

PostHog derives the organization ID from the authenticated project and forwards the request to the corresponding organization-scoped Duckgres endpoint.
The browser never supplies an organization ID and never calls Duckgres directly.
Both PostHog actions require `warehouse_view:read`.

Duckgres only returns sanitized worker data.
The response excludes SQL text, usernames, client addresses, pod names, images, credentials, trace IDs, and control-plane ownership details.

### MCP access

Authenticated MCP clients can request the same organization-scoped data through these tools:

- `managed-warehouse-monitoring-get` for the current worker and workload snapshot
- `managed-warehouse-metric-history-get` for one operational metric over a trailing time window

Both tools require `warehouse_view:read` and are available when the `data-warehouse-scene` feature is enabled.
They use the active project to derive the organization and do not accept an organization ID from the caller.
The returned values describe operational activity and capacity, not invoiced usage.

## Snapshot

The snapshot contains:

- Warehouse state and configured worker limits
- Current worker, allocated CPU, allocated memory, session, running-query, and queued-connection totals
- One sanitized row per non-terminal worker, with its allocation, heartbeat, and optional live session progress
- Control-plane response coverage

Allocated CPU and memory describe the configured worker size, not measured CPU or memory utilization.
The `max_vcpus` setting limits active admitted session vCPUs; it is not a ceiling on the total CPU allocated to warm and active workers.
The UI must keep that distinction in labels and help text.

Legacy and default-profile workers persist empty resource sentinels.
Duckgres resolves those workers against the deployment defaults that provision their pods, rather than guessing from current organization defaults.
Query progress is returned as unavailable when DuckDB cannot estimate it, instead of failing the full snapshot.

Live sessions are held in memory by individual control-plane replicas.
Duckgres fans out the live portion of the snapshot and returns `cp_responders`, `cp_total`, and `partial`.
When coverage is partial, the UI labels live totals as incomplete instead of presenting missing replicas as zero activity.

## Historical metrics

The time-series endpoint accepts only named metrics and validated windows.
Duckgres maps each name to server-owned PromQL and applies the organization selector before querying Prometheus.
It is not an arbitrary PromQL proxy.

The dashboard displays query rate and outcomes, query latency, active sessions, worker acquisition latency and source, storage size, and worker crashes.
Each response includes a unit and labeled series so the UI can format values without guessing.

The dashboard loads historical data when the selected range changes or the user refreshes it.
The current snapshot polls more frequently while work is active and less frequently while the warehouse is idle.
If a refresh fails, the UI preserves the last successful data and shows how to retry.

## Usage scope

This first version reports operational activity and allocated capacity.
It does not calculate invoice totals or read Duckgres's billing delivery buffer, because acknowledged billing buckets are deleted after delivery.
Historical billable compute and storage belong in a billing-backed API rather than this monitoring path.
