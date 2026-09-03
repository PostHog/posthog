# Injecting context

Tell the agent what the user is looking at. While a provider is registered, every message sent from the surface is silently prefixed with a context block; the user sees only their own text, and history replay strips the block back off.

## The item shape

`AttachedContextItem` (`products/posthog_ai/frontend/types/contextTypes.ts`, exported from `api/types`):

| Field          | Meaning                                                                                                                                                                                                             |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`         | **An arbitrary string**, never an enum. `'insight'`, `'dashboard'`, `'trace'`, `'text'`, `'hog_flow_editor_state'` — invent what fits. The one reserved value is `'instructions'`, which routes to trusted context. |
| `key`          | The entity identifier the agent will resolve — id, `short_id`, trace id.                                                                                                                                            |
| `label`        | Human-readable chip label.                                                                                                                                                                                          |
| `value`        | Free-text payload, for items that have no keyed entity.                                                                                                                                                             |
| `hidden`       | Rendered into the block but never shown as a composer chip.                                                                                                                                                         |
| `dismissGroup` | Items sharing a group are dismissed together.                                                                                                                                                                       |

Items are flattened across providers and deduped by `${type}:${key ?? value}` (`attachedContextItemKey`).

## Three ways to register

**A component** — the normal path:

```tsx
import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

useAttachedContext(dashboard ? [{ type: 'dashboard', key: dashboard.id, label: dashboard.name ?? undefined }] : null)
```

Pass `null` while the entity is loading, or `{ active: false }`. Real caller: `frontend/src/scenes/dashboard/Dashboard.tsx`.

**JSX only** — `<AttachedContextProvider items={items} />` from `api/primitives`, a render-null wrapper over the same hook.

**A kea logic** — register through a disposable (see `/using-kea-disposables`); the returned cleanup deregisters on unmount, so no `beforeUnmount` is needed:

```ts
afterMount(({ actions, cache, values }) => {
  cache.disposables.add(
    () => {
      actions.registerContext('my-scene', [{ type: 'dashboard', key: values.dashboard.id }])
      return () => actions.deregisterContext('my-scene')
    },
    'attachedContext',
    { pauseOnPageHidden: false }
  )
})
```

`pauseOnPageHidden: false` is **required**, not stylistic. The registration costs nothing while idle, and the default hide-pause would silently drop context from a queued follow-up that flushes while the tab is hidden. `contextPickerLogic` is the exemplar.

Re-dispatching `registerContext` with the same provider id is an upsert — do it from a `subscriptions` handler when the resource changes.

**A whole scene** — `useSceneAgentPanel` wraps the hook plus welcome headlines plus gated auto-open of the side panel. Prefer it for a scene.

## Identifiers, not object shapes

The context block rides on **every message** in the conversation, so a serialized entity is a per-turn cost that never goes away. Send the reference and let the agent fetch details with your MCP tools — which is also why the tool has to exist first.

The exception is **unsaved progress the agent cannot fetch**: live editor or form state. When you send that, budget it. `products/workflows/frontend/Workflows/workflowAgentContext.ts` is the reference implementation:

- `EDITOR_STATE_MAX_CHARS = 64_000`. Over budget, it **elides** the heavy nested parts and replaces them with a marker telling the agent which tool to call for the full value. Elision keeps the JSON parseable; blind truncation does not.
- Derived weight is dropped before measuring — rendered html is not sent when the design it was rendered from is already there.
- A trusted instruction tells the agent to prefer the live state over a fetched definition when reading, and to fetch when it needs the persisted one.

## Redact secrets

Saved secrets never reach the frontend, but a secret typed into a form and not yet saved sits in cleartext in your live form state — and a step may carry only a `template_id`, so which fields are secret is only knowable from a loaded schema.

`redactWorkflowSecretInputs` in the same file shows the shape: redact by schema, and **fail closed** when the schema is unavailable (still loading, fetch failed, template deleted) by redacting every value. It also clears compiled bytecode of a redacted entry, because the bytecode can embed the literal.

## Untrusted by design

Non-`instructions` items land in `<posthog_untrusted_context>`, behind hardening prose that tells the agent this is data, not direction. That is what makes it safe to inject whatever the user typed — and you should, since their unsaved work is usually the most useful thing you have. Do not sanitize user text into blandness; put it in the untrusted block and leave it intact.

## Dedupe and dismissal

Deduping is automatic and **task-scoped**, covering the whole resume chain of runs, in two layers: keys marked right after each send, and the durable layer derived from context blocks found in replayed history (so it survives reloads, other tabs, and other users' sessions). `text` items are never deduped — repeated text is intentional.

Chips render **all** of `contextItems`, whatever provider contributed them. Closing a chip your provider owns dispatches `dismissContext(key)`, and dismissal **survives re-registration** — a scene bridge that upserts on every read must not resurrect a chip the user closed. This is what `dismissGroup` is for: pair a visible chip with the hidden payload items it stands for, so closing the chip actually detaches the payload instead of only hiding the chip.

Users can also attach context themselves through the composer's `@` affordance (`AttachedContextBar` from `api/primitives`, backed by `contextPickerLogic` as the `user-picker` provider). Selections become flat refs via `taxonomicItemToAttachedContext` — again no entity loading.
