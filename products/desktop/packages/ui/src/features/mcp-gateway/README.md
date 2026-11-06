# MCP gateway (desktop)

The desktop UI for the team MCP gateway: servers home, server/agent/member detail pages, team settings, and the audit log.
Rendered by `../mcp-servers/components/McpServersView.tsx` when the `MCP_GATEWAY_FLAG` feature flag is on.

## Keep the web app in sync

This is one half of a deliberately duplicated UI.
The PostHog web app ships its own implementation at `products/mcp_store/frontend/gateway/` (Kea + LemonUI), plus a Settings-embedded variant in `products/mcp_store/frontend/settings/`.
Both consume the same gateway REST API (`products/mcp_store/backend/presentation/gateway_views.py`).
The desktop's request/response types are hand-written mirrors in `packages/api-client/src/mcp-gateway.ts`, so serializer changes must update those too.
The MCP store feature set always changes for both apps together: when you change the feature set or UI here, make the equivalent change in the web app in the same PR, or open an explicitly linked follow-up — and vice versa.

`products/mcp_store/README.md` is the canonical doc for the whole product, including the directory mapping between the two apps.
