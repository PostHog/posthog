# MCP servers (desktop)

The desktop marketplace UI for the MCP store: browse the curated catalog, connect servers, and manage installations.
`components/McpServersView.tsx` is the entry point; when the `MCP_GATEWAY_FLAG` feature flag is on it renders the team gateway experience from `../mcp-gateway/` instead of the legacy marketplace.

## Keep the web app in sync

This is one half of a deliberately duplicated UI.
The PostHog web app ships its own implementation of the same product at `products/mcp_store/frontend/` (Kea + LemonUI; the marketplace lives in `scene/`).
Both consume the same backend (`products/mcp_store/backend/`) and the same feature flags, but share no UI code.
The MCP store feature set always changes for both apps together: when you change the feature set or UI here, make the equivalent change in the web app in the same PR, or open an explicitly linked follow-up — and vice versa.

`products/mcp_store/README.md` is the canonical doc for the whole product, including the directory mapping between the two apps.
