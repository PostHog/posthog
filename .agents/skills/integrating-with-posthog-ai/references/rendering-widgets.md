# Rendering tool cards in a thread

Export a typed declaration list from `products/<product>/frontend/posthogAiToolRenderers.tsx`.
Add one direct import and one spread to `frontend/src/posthogAiToolRenderers.ts` for your product.
Keep individual entries with their product; import no scenes or broad component barrels from declaration modules.
Use **type-only** imports from `api/tools` for the contract, so declarations cannot create a runtime cycle with the registry.

The registry initializes synchronously from built-ins and this manifest before rendering.
The manifest is the sole extension mechanism: there is no runtime registration, subscription, or asynchronous initialization.
`toolRegistry.lookup` and `lookupToolRenderer` remain available; keep headless `api/logics` and `api/types` free of registry imports.

```tsx
import { IconBolt } from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'

export const posthogAiToolRenderers: ToolRegistryEntry[] = [
  {
    key: 'cdp-functions-partial-update',
    displayName: 'Update function',
    icon: <IconBolt />,
    PermissionPreview: lazyWithRetry(() =>
      import('./HogFunctionPermissionPreview').then((m) => ({ default: m.HogFunctionPermissionPreview }))
    ),
    requiresPostHogOrigin: true,
  },
]
```

Reference lists: `products/posthog_ai/frontend/posthogAiToolRenderers.tsx` for data widgets,
`products/error_tracking/frontend/posthogAiToolRenderers.tsx` for product-owned error-tracking widgets,
and `products/cdp/frontend/posthogAiToolRenderers.tsx` for a lazy permission preview.
Declaration lists live at the product frontend root, outside `api/`. Implementations that use another
product’s internals belong with that product. Use PostHog AI’s public `api/tools` helpers for the tool-card
contract and generic output parsing; shared `frontend` dependencies are allowed.
Implementations stay product-owned and load only on use through `lazyWithRetry`.

## The entry

| Field                   | Meaning                                                        |
| ----------------------- | -------------------------------------------------------------- |
| `key`                   | Inner exec tool name, or the wire name for a built-in.         |
| `displayName`           | Card title text.                                               |
| `icon`                  | Card icon.                                                     |
| `Renderer`              | Result card component. Omit for a preview-only entry.          |
| `PermissionPreview`     | Approval evidence component receiving `{ request, fallback }`. |
| `requiresPostHogOrigin` | Match only calls from the trusted PostHog server.              |

Set `requiresPostHogOrigin: true` for PostHog entities. A colliding tool name from another server must keep generic rendering.
Unknown tools and preview-only entries use the generic result card.

## A card is two header lines plus an accordion

Every renderer wraps its content in `ToolActivity`, which exposes exactly two always-visible lines:

- `title` — what happened.
- `subtitle` — the **one** most salient input: a command, a path, a name.

**Everything else your tool produces goes in the collapsible `body`** — parsed output, lists, file contents, diffs, raw text. The body auto-expands while the tool runs and collapses when it completes, so a thread with twenty tool calls stays scannable and a reader expands only the cards they care about.

Reserve `children` (always visible) for genuinely interactive payloads that would be useless collapsed — something the user must act on. Output is never that. When in doubt, it goes in the accordion.

## Permission previews

`PermissionPreview` receives `{ request, fallback }`, typed as `PermissionPreviewProps` from `api/tools`.
Return `fallback` when there is no available matching mounted configuration or no changes to show.
Do not mount or fetch a product scene to produce a preview.
`PermissionInput` supplies its evidence block as fallback, and wraps the preview in `Suspense` and `PostHogErrorBoundary`.
Both boundaries use that evidence fallback; approval controls remain outside them and stay usable during loading or failure.
Errors retain the `posthog_ai_permission_preview` feature tag, and a new permission request resets the error boundary.

Verify declarations are available from a registry-only import and do not evaluate lazy implementations.
Render a matching card to check its skeleton resolves. Exercise preview loading, errors, missing/mismatched state,
and successful diffs while keeping approvals usable. Keep trusted-origin and unknown-tool fallback coverage.

## Not to be confused with MCP UI apps

The `@posthog/mcp-ui` components under `products/*/mcp/apps/`, declared as `ui_apps` in a product's `mcp/tools.yaml`, are a **different mechanism**. They render tool results in _external_ MCP clients such as Claude Desktop, served through `services/mcp/`, and nothing under the PostHog AI frontend imports them. They do not appear in PostHog AI threads.

If the ask is "make our tool results look good in Claude Desktop", that is `/implementing-mcp-ui-apps`. If it is "make our tool results look good in PostHog AI", it is this file.
