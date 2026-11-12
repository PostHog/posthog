---
paths:
  - 'products/mcp_store/**'
  - 'products/desktop/packages/api-client/src/mcp-gateway.ts'
---

PostHog Desktop is no longer maintained, so MCP store UI changes in the web app (`products/mcp_store/frontend/`) do not need a Desktop counterpart.
Desktop still builds against this backend in CI.
When you change a serializer the gateway UI consumes, keep the desktop's hand-written type mirrors in `products/desktop/packages/api-client/src/mcp-gateway.ts` compiling, or the Desktop checks fail.
