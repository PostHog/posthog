# Rendering tool cards in a thread

Register a renderer and your product's tool calls display as a real card instead of the generic MCP fallback. The seam is `registerToolRenderers` from `api/tools` — a module-level side effect, no hooks and no dynamic registration.

```tsx
import { registerToolRenderers } from 'products/posthog_ai/frontend/api/tools'

registerToolRenderers([
  {
    key: 'cdp-functions-partial-update',
    displayName: 'Update function',
    icon: <IconBolt />,
    renderPermissionPreview: renderPartialUpdatePreview,
    requiresPostHogOrigin: true,
  },
])
```

Real caller: `frontend/src/scenes/hog-functions/configuration/registerHogFunctionToolPreviews.tsx`.

## The entry

| Field                     | Meaning                                                                 |
| ------------------------- | ----------------------------------------------------------------------- |
| `key`                     | The inner exec tool name, or the wire tool name for a built-in.         |
| `displayName`             | Card title text.                                                        |
| `icon`                    | Card icon.                                                              |
| `Renderer`                | Draws the **result** card. Optional — omit it for a preview-only entry. |
| `renderPermissionPreview` | Draws the approval prompt shown **before** a write runs.                |
| `requiresPostHogOrigin`   | Only match calls that came through the trusted PostHog server.          |

Set `requiresPostHogOrigin: true` for anything that renders PostHog entities. Without it, a tool of the same name from another MCP server would render through your card.

Registration is by import, so call it once from your scene's entrypoint (or a small `register*.tsx` module the entrypoint imports for its side effect). Re-registering the same `key` overwrites. Wrap a heavy `Renderer` in `lazyWithRetry` so it does not weigh down the chunk that registers it.

The built-in PostHog widgets — insights, dashboards, recordings, error tracking issues, notebooks, query results — live in `products/posthog_ai/frontend/components/tool/widgets/` and self-register the same way. Read `registerDataToolRenderers.tsx` there as the reference implementation; it is the same public seam, not a privileged path.

## A card is two header lines plus an accordion

Every renderer wraps its content in `ToolActivity`, which exposes exactly two always-visible lines:

- `title` — what happened.
- `subtitle` — the **one** most salient input: a command, a path, a name.

**Everything else your tool produces goes in the collapsible `body`** — parsed output, lists, file contents, diffs, raw text. The body auto-expands while the tool runs and collapses when it completes, so a thread with twenty tool calls stays scannable and a reader expands only the cards they care about.

Reserve `children` (always visible) for genuinely interactive payloads that would be useless collapsed — something the user must act on. Output is never that. When in doubt, it goes in the accordion.

## Permission previews

`renderPermissionPreview` runs at the approval prompt, before the tool executes, and receives the pending request record. It is worth writing for any destructive or hard-to-reverse write: show _what will change_, not just the tool name, so the user approves a real thing rather than a label. An entry can carry a preview and no `Renderer` at all.

## Not to be confused with MCP UI apps

The `@posthog/mcp-ui` components under `products/*/mcp/apps/`, declared as `ui_apps` in a product's `mcp/tools.yaml`, are a **different mechanism**. They render tool results in _external_ MCP clients such as Claude Desktop, served through `services/mcp/`, and nothing under the PostHog AI frontend imports them. They do not appear in PostHog AI threads.

If the ask is "make our tool results look good in Claude Desktop", that is `/implementing-mcp-ui-apps`. If it is "make our tool results look good in PostHog AI", it is this file.
