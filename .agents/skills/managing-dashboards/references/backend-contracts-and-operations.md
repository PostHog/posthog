# Backend contracts and operations

## Resource lifecycle

Dashboards and tiles use soft deletion. Do not replace it with hard deletion.

- `Dashboard.objects` hides deleted dashboards. `objects_including_soft_deleted` supports restore paths.
- Dashboard deletion can also delete insights when the request asks for it. Check shared insight and restore behavior.
- Deleting a tile keeps its underlying insight, text, button, or widget row when another relation needs it.
- Moving and copying must preserve the one-related-object tile constraint and destination permissions.
- Use a narrow `transaction.atomic()` block for a multi-row dashboard mutation.
- A bulk update bypasses model signals. Synchronize dependent resources explicitly after a bulk update.

Check `products/dashboards/backend/models/dashboard_tile.py` and `products/dashboards/backend/api/dashboard.py` before you change lifecycle behavior.

## Project tree, tags, and resource transfer

Dashboards are project-tree resources, not only API rows. Read this section when a persisted field or relation can transfer between projects.

- `Dashboard` uses `FileSystemSyncMixin`. Create, rename, move, delete, and restore can update file-system entries.
- Keep dashboard folder data private on shared responses.
- Preserve tag behavior when a custom serializer create or update path bypasses a mixin.
- Update resource-transfer visitors when a new persisted field should copy between projects.
- Exclude derived state from transfers. Existing visitors exclude sharing, refresh, access, and cache fields.
- Check that a transferred dashboard has valid team ownership and no source-project-only identifiers.

## Lists, discovery, and product-created dashboards

Dashboard list behavior is a separate contract from dashboard detail.

- Preserve pinned ordering, search, tags, folder data, and unlisted-dashboard exclusion.
- Check list query annotations and prefetches when you add a list field. Avoid per-row file-system or tag queries.
- Dashboard reads update `last_accessed_at`. Check write amplification when you add polling, embeds, or another read path.
- Product-created unlisted dashboards need stable lookup data and concurrent-create protection.
- Keep product-created dashboards out of normal lists unless the product explicitly exposes them.

## API, schema, and MCP contracts

Dashboard behavior has REST and generated frontend consumers. It also has MCP consumers when the changed API operation is enabled in `products/dashboards/mcp/tools.yaml`.

1. Add serializer schema annotations for every new request or response field.
2. Run `hogli build:openapi` after API contract changes.
3. Update `products/dashboards/mcp/tools.yaml` only when the changed operation is MCP-enabled or becomes MCP-enabled.
4. Regenerate MCP code only when the OpenAPI operation or tool definition changes.
5. Check required API scopes. Dashboard reads, writes, and query execution use different scopes.
6. Keep one-off filter and variable overrides non-persistent unless the endpoint explicitly persists them.
7. Keep shared-token rules. Shared requests ignore dashboard filter and variable overrides.

Test REST and MCP behavior separately. An MCP response can intentionally omit fields that the REST endpoint returns.

## Streaming and progressive delivery

Read this section only when the change affects dashboard tile delivery or initial load. `stream_tiles` sends dashboard metadata and tiles through Server-Sent Events.

- Send metadata before remaining tiles.
- Keep tile order stable for the selected layout size.
- Treat one tile serialization failure as a tile error. Do not fail the whole dashboard stream.
- Send a completion event after all tiles.
- Support both ASGI and WSGI delivery paths.
- Do not add database work inside the async generator unless the thread and connection behavior is safe.
- Check client cancellation and stale stream responses when dashboard, filters, variables, or placement changes.
- Check the `chained_dashboard_tile_refresh` gate and every related `ComputeSurface` before you change a refresh default.

Use the normal retrieve endpoint and `stream_tiles` as two separate read contracts.

## Limits, gates, and abuse resistance

Check limits before you add a path that creates, loads, or runs dashboard work.

- Dashboard creation uses `LimitKey.MAX_DASHBOARDS_PER_TEAM`.
- Public and embedded access must not bypass quotas or product access checks.
- Bound request payloads, tile IDs, filter sizes, and pagination before they reach query execution.

Read `manage-dashboard-widgets` for widget-specific limits, gates, and throttles.

## Audit, analytics, subscriptions, and observability

Dashboard changes are product events and audit events.

- Preserve model activity logging for dashboard and widget changes.
- Preserve user-action events for dashboard and tile create, update, delete, and filter changes.
- Keep dashboard access and cache metrics classified by human, shared, embedded, and API access.
- Preserve endpoint monitoring. Assess SLO coverage for a new dashboard delivery or query path.
- Check dashboard subscriptions and the subscribe nudge when you change dashboard navigation, permissions, or the subscription destination.
- The subscribe nudge uses a cache sentinel and a durable notification check. Preserve both forms of deduplication.

## Backend test matrix

| Change                   | Test boundary                                                                    |
| ------------------------ | -------------------------------------------------------------------------------- |
| Persisted model field    | Migration, serializer, OpenAPI, generated types, and MCP schema                  |
| Create or delete         | Team quota, soft delete, activity log, file-system sync, and restore             |
| Move, copy, or duplicate | Source and destination access, transaction rollback, and tile uniqueness         |
| Read endpoint            | REST and stream behavior, shared sanitization, cache policy, and error payload   |
| Query endpoint           | Scope, throttle, access method, cache outcome, cancellation, and partial failure |
| Template or transfer     | Old payload, source-specific reference, target team, and excluded derived fields |
| Subscription path        | Permission, duplicate delivery, cache loss, and notification failure             |
