---
name: integrating-with-posthog-ai
description: 'Wire a PostHog product surface into the PostHog AI agent from the frontend. Use when attaching scene or entity context, injecting instructions to steer the agent, reacting to the agent calling a tool, applying an agent edit back into an open form, or rendering a product tool card in a thread.'
---

# Integrating a product with PostHog AI

The user-facing doc is [`products/posthog_ai/README.md`](../../../products/posthog_ai/README.md). This skill is how to _do_ the work: pick the right seam, avoid the two mistakes that matter, and stop before the deep end.

## First: is this a frontend job at all?

There is **no backend integration API**. An integration has two halves, and the frontend half depends on the backend half:

1. **Capability** — the agent reads and writes your entities through **MCP tools**. If no tool can resolve the thing you want to talk about, start there: `/implementing-mcp-tools`, `products/<name>/mcp/tools.yaml`.
2. **Cooperation** — the frontend seams below.

Injected context carries _references_, not data. A reference the agent cannot resolve with a tool is a dead end, so confirm the tool exists before you inject the ref.

## Pick the seam

| The job                                                                                                      | Seam                 | Import from                        | Use it?                         | Reference                                                         |
| ------------------------------------------------------------------------------------------------------------ | -------------------- | ---------------------------------- | ------------------------------- | ----------------------------------------------------------------- |
| The agent should know what the user is looking at, including unsaved work                                    | Attached context     | `api/logics`                       | **Recommended**                 | [injecting-context.md](references/injecting-context.md)           |
| Steer how the agent behaves here — which tools to prefer, what "this" means on this page, or hand it a skill | Trusted instructions | `api/logics`                       | **Recommended**                 | [injecting-instructions.md](references/injecting-instructions.md) |
| The page should update when the agent does something                                                         | Tool-event bus       | `api/logics`                       | **Recommended**                 | [reacting-to-tool-calls.md](references/reacting-to-tool-calls.md) |
| Your tool's calls should render as a real card, not the generic fallback                                     | Tool registry        | `api/tools`                        | **Recommended**                 | [rendering-widgets.md](references/rendering-widgets.md)           |
| Build your own agent UI out of the thread, composer, and stream primitives                                   | Run primitives       | `api/runSurface`, `api/primitives` | **Not recommended** — see below | `products/posthog_ai/frontend/README.md`                          |

The first four are the product integration. The fifth exists for the three surfaces that _host_ an agent run — the Max scene, the signals inbox, and the tasks runner — not for products that want to cooperate with one. Reaching for it by default is the main way this goes wrong.

Whole scene at once: `useSceneAgentPanel({ sceneKey, contextItems, headlines })` from `frontend/src/scenes/max/useSceneAgentPanel.ts` bundles context, welcome headlines, and gated auto-open of the side panel. Start there for a scene; drop to the individual hooks for one component. `products/workflows/frontend/Workflows/WorkflowScene.tsx` is the exemplar.

## The import rule

Always a domain-scoped `api/<module>` entry, never a deep path, and there is deliberately no root barrel:

```ts
import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
```

Pick the narrowest module. `api/logics` and `api/types` are headless; `api/primitives` drags in markdown and virtualization; `api/tools` registers built-ins at module load, so importing it is a side effect that is not tree-shaken. A status badge that imports the wrong tier doubles its chunk.

## The two mistakes that matter

**1. Putting variable data in trusted context.** `type: 'instructions'` items land in `<posthog_trusted_context>` — guidance the agent follows. Everything else lands in `<posthog_untrusted_context>`, behind hardening prose. So:

- Instructions carry **only your own build-time strings**. Never a user-entered name, an ingested value, or anything interpolated from one. A crafted entity name in trusted context is a prompt injection against whoever reads the thread next.
- Untrusted context is where user data belongs, and injecting it freely is the point — the user's unsaved editor state is usually the most useful thing you have.
- If a pointer must vary (which id is open, which step is selected), put it on an untrusted item and have the static instruction refer to it by field name.

**2. Sending object shapes instead of identifiers.** The context block rides on _every_ message in the conversation. Send `{ type, key, label }` and let the agent fetch details through your MCP tools. The exception is unsaved state the agent cannot fetch — budget it (`workflowAgentContext.ts` caps at 64k chars and elides rather than truncates) and redact secrets, which sit in cleartext in live form state even though saved secrets never reach the frontend.

## Stop at seam 4

The run primitives are public — `RunSurface`, `ReadonlyRunSurface`, `EmbeddedRunner`, the `Thread` atoms, `runStreamLogic` — but building a custom agent UI on them is not a product integration. It means owning stream binding, composer and queue state, permission routing, and the eager-vs-lazy tier choice that decides your bundle size. There is no default layout.

If that is genuinely the task, read [`products/posthog_ai/frontend/README.md`](../../../products/posthog_ai/frontend/README.md) and [`AGENTS.md`](../../../products/posthog_ai/frontend/AGENTS.md) first, and copy one of the two reference implementations (the signals inbox detail views, or `scenes/TaskTracker/components/TaskRunChat.tsx`) rather than composing from scratch.

## Do not touch

- **The LangGraph runtime is frozen.** No new `useMaxTool` registrations, no new `MaxUIContext` fields, no new `maxContext` selectors on scene logics. Use attached context and the tool-event bus instead.
- **The coupling gate.** Nothing under `products/posthog_ai/frontend` may import `scenes/max`, `maxThreadLogic`, `maxContextLogic`, or the conversations API. Max is a consumer of that surface, not a dependency of it. If the surface is missing something you need, lift it to a generic prop or selector there — never special-case a consumer inside it.

## Verify

- `pnpm --filter=@posthog/frontend typescript:check` for the types.
- Run the app and open the side panel on your page. Context is invisible by design, so check it landed: an attached item that is not `hidden` shows as a chip in the composer's context bar, and the agent should be able to answer a question about the thing you attached without being told its id.
- For a reactivity seam, ask the agent to make the change and confirm the open page updates. Then reload the page — your handler must **not** fire again, because replay events are suppressed by default.
