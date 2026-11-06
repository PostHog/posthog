# MCP server manager (desktop)

The add-custom-MCP-server flow (dialog, form, and connect hook), used by the marketplace in `../mcp-servers/` and by agent configuration.

## Keep the web app in sync

The PostHog web app ships its own custom-server flow at `products/mcp_store/frontend/scene/AddCustomServerForm.tsx` against the same backend.
The MCP store feature set always changes for both apps together: when you change the flow here, make the equivalent change in the web app in the same PR, or open an explicitly linked follow-up — and vice versa.

See `../mcp-servers/README.md` and `products/mcp_store/README.md` (the canonical doc for the whole product).
