---
paths:
  - 'products/mcp_store/**'
  - 'products/desktop/packages/ui/src/features/mcp-servers/**'
  - 'products/desktop/packages/ui/src/features/mcp-gateway/**'
  - 'products/desktop/packages/ui/src/features/mcp-server-manager/**'
  - 'products/desktop/packages/api-client/src/mcp-gateway.ts'
---

The MCP store UI is implemented twice against the same backend and feature flags, with no shared UI code:
the web app (`products/mcp_store/frontend/`, Kea + LemonUI) and PostHog Desktop
(`products/desktop/packages/ui/src/features/mcp-servers/`, `mcp-gateway/`, `mcp-server-manager/`; TanStack Query + quill).
The feature set always changes for both apps together: when you change the feature set or UI in one app,
make the equivalent change in the other, in the same PR or an explicitly linked follow-up.
Changes to serializers the gateway UI consumes also need the desktop's hand-written type mirrors in
`products/desktop/packages/api-client/src/mcp-gateway.ts` updated.
See "Keep the desktop UI in sync" in `products/mcp_store/README.md` for the directory mapping.
