# RBAC, sharing, and embeds

## Access rules

Check both server and client behavior.

- The server is the authority for view, edit, create, delete, move, copy, and refresh actions.
- `Dashboard.restriction_level` controls collaboration restrictions.
- Collaborator access is an EE sub-route under `dashboards/<id>/collaborators`.
- Dashboard sharing uses the core `SharingConfigurationViewSet` under `dashboards/<id>/sharing`.
- Public and embedded callers must not gain mutation rights through an endpoint that the UI hides.
- A related insight or widget can have stricter access than its dashboard. Preserve its access checks and safe error response.

## Shared output is a separate contract

For a public share, check every field in the response and every UI action.

- Hide author, editor, folder, and other private metadata.
- Use the shared-safe widget metadata serializer for widget tiles.
- Do not return live widget query results to public viewers.
- Do not permit a public, shared, or export viewer to force a server-side insight or widget refresh.
- Keep the shared cache clamp. Anonymous demand must not trigger expensive recomputation.
- Test an error response. Error serialization must not reveal fields that normal shared serialization hides.

`DashboardTileSerializer`, `SharedDashboardWidgetMetadataSerializer`, and `DashboardTileErrorSerializer` in `products/dashboards/backend/api/dashboard.py` define important response boundaries.

## Embedded dashboards

Embedded dashboards have a distinct access metric and can have distinct host constraints.

- Classify access with `dashboard_access_method` in `products/dashboards/backend/access.py`.
- Preserve the embedded access method when you add a new read or refresh path.
- Check the host surface for width, navigation, filter state, and authenticated user assumptions.
- Do not rely on a full dashboard page or a desktop viewport.

## Sharing changes

When a dashboard becomes shared, check existing tiles before you publish the state.

- Use the server-side sharing publish gate for insight tiles.
- Check every tile type. A new type needs an explicit public-safety decision.
- Check changes to existing dashboards. Public sharing can expose stored configuration from rows created before the change.
- Test enable, disable, read, and denied mutation paths.

## Minimum test matrix

| Actor or surface       | Read                                      | Mutate                                | Refresh                         |
| ---------------------- | ----------------------------------------- | ------------------------------------- | ------------------------------- |
| Project viewer         | Allowed only when resource access permits | Denied                                | Only if the endpoint permits it |
| Project editor         | Allowed                                   | Allowed within dashboard restrictions | Allowed                         |
| Dashboard collaborator | Follow assigned privilege                 | Follow assigned privilege             | Follow assigned privilege       |
| Public shared viewer   | Safe read-only payload                    | Denied                                | Denied                          |
| Embedded viewer        | Follow host and resource access           | Denied unless explicitly supported    | Must stay bounded               |
| Export renderer        | Render-safe payload                       | Denied                                | Denied                          |
