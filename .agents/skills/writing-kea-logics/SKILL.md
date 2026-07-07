---
name: writing-kea-logics
description: Guide for writing or reviewing PostHog kea logic files (`*Logic.ts` / `*Logic.tsx`). Use when creating a new logic, adding actions/reducers/selectors/listeners/loaders/forms/router bindings, choosing between reducer vs selector vs cache, deciding between listeners and `kea-subscriptions`, wiring React with `useValues`/`useActions`/`BindLogic`, or onboarding to kea conventions. Read keajs.org for upstream API; this skill captures PostHog-specific conventions and idioms.
---

# Writing kea logics

PostHog uses [kea](https://keajs.org) as the state container for the frontend. Almost
all non-trivial business logic lives in a `*Logic.ts` / `*Logic.tsx` file, not in
React. We may be on a kea pre-release ahead of the version the keajs.org docs
cover — when in doubt, check `pnpm-workspace.yaml` for the pinned version.

This skill captures the PostHog-specific conventions on top of the upstream
[kea docs](https://keajs.org). When in doubt about a builder's signature, go upstream.
When in doubt about whether to use it, read here.

## Use this skill when

- Creating a new `*Logic.ts` / `*Logic.tsx` file
- Adding builders to an existing logic (actions, reducers, selectors, listeners, loaders, forms)
- Choosing between `reducer` vs `selector` vs `cache` vs `loader` for a piece of state
- Wiring a React component to a logic
- Reviewing a PR that introduces or modifies a kea logic
- Reviewing code that uses React hooks where a logic would be more idiomatic

## Companion skills (do not duplicate)

- [using-kea-disposables](../using-kea-disposables/SKILL.md) — `setInterval`, `addEventListener`,
  and any other resource that needs cleanup.

If your work overlaps it, read the companion skill first.

## Core principles

1. **Business logic lives in a logic, not in a component.**
   [CLAUDE.md](../../../CLAUDE.md) is explicit: "If there is a kea logic file, write all
   business logic there, avoid React hooks at all costs." Hooks are for view concerns.

2. **One concept, one source of truth.** Pick exactly one of: action-driven reducer,
   derived selector, async loader. Don't mirror the same value into multiple places.

3. **Prefer listeners over `kea-subscriptions`.** Subscriptions install a redux
   subscription that re-runs on every dispatch and is measurably slower. Listen to the
   action that changed the value instead. See
   [references/reacting-to-changes.md](references/reacting-to-changes.md).

4. **Generated types are the contract.** Every logic has an auto-generated
   `*LogicType.ts` next to it. Import with `import type` and pass it as the kea type
   parameter. Never edit the generated file.

5. **Resources that need cleanup go through `cache.disposables`.** See the
   [using-kea-disposables](../using-kea-disposables/SKILL.md) skill.

## Anatomy at a glance

```ts
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { fooLogicType } from './fooLogicType'

export interface FooLogicProps {
  fooId: string
}

export const fooLogic = kea<fooLogicType>([
  props({} as FooLogicProps),
  key((props) => props.fooId),
  path((key) => ['scenes', 'foo', 'fooLogic', key]),
  connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
  actions({ setName: (name: string) => ({ name }) }),
  loaders(({ props }) => ({
    foo: [null as Foo | null, { loadFoo: async () => api.foos.get(props.fooId) }],
  })),
  reducers({ name: ['', { setName: (_, { name }) => name }] }),
  selectors({ nameUpper: [(s) => [s.name], (name): string => name.toUpperCase()] }),
  listeners(({ actions }) => ({
    loadFooSuccess: () => {
      /* ... */
    },
  })),
  afterMount(({ actions }) => {
    actions.loadFoo()
  }),
])
```

Conventional block order: `props` → `key` → `path` → `connect` → `actions` → `forms` → `loaders` →
`reducers` → `selectors` → `sharedListeners` → `listeners` → `subscriptions` (rare) →
`windowValues` → `urlToAction` / `actionToUrl` → `afterMount` / `propsChanged` / `beforeUnmount`.

You almost never need all of those — half a dozen blocks is typical. Pick the ones
the logic actually uses and leave the rest out.

## Decision flow — pick the right container before you start

Most kea bugs come from picking the wrong container for a piece of state. Work
through this before reaching for any builder:

1. **Does it come from an HTTP call?** Use a [loader](references/loading-data.md).
2. **Can it be computed from other state?** Use a `selector`.
3. **Does an action change it, and does the UI need to re-render when it changes?**
   Use a `reducer`.
4. **Is it a timer, listener, or other disposable resource?** Use `cache.disposables`
   — see [using-kea-disposables](../using-kea-disposables/SKILL.md).

`cache.foo` is an escape hatch for transient flags the UI never reads — reach for it
last, not first. See [references/state-decision.md](references/state-decision.md)
for the full breakdown.

## Pattern index

Each reference covers one job-to-be-done with the pattern shape, why it's the right
shape, and the trade-offs. File citations inside references are "examples in the wild
today" — they age, so the pattern itself is the source of truth.

| You want to...                                     | Read                                                                   |
| -------------------------------------------------- | ---------------------------------------------------------------------- |
| Decide between reducer / selector / cache / loader | [references/state-decision.md](references/state-decision.md)           |
| Load data from the API                             | [references/loading-data.md](references/loading-data.md)               |
| Poll an endpoint or refresh on an interval         | [references/polling.md](references/polling.md)                         |
| Build a form                                       | [references/forms.md](references/forms.md)                             |
| Sync state with the URL                            | [references/routing.md](references/routing.md)                         |
| Persist state across reloads                       | [references/persisting-state.md](references/persisting-state.md)       |
| React to a value change                            | [references/reacting-to-changes.md](references/reacting-to-changes.md) |
| Have multiple instances of one logic               | [references/keyed-logics.md](references/keyed-logics.md)               |
| Share state across logics or a component subtree   | [references/connecting-logics.md](references/connecting-logics.md)     |
| Test the logic                                     | [references/testing.md](references/testing.md)                         |
| Recognise a pattern you should convert on sight    | [references/anti-patterns.md](references/anti-patterns.md)             |

## Types and typegen

```ts
import type { fooLogicType } from './fooLogicType'
export const fooLogic = kea<fooLogicType>([...])
```

Generated `*LogicType.ts` files are produced by `kea-typegen` (we use the
`3.6.2-leakfix.x` private fork). Commands:

- `pnpm --filter=@posthog/frontend typegen:watch` — watch mode while writing logics
- `pnpm --filter=@posthog/frontend typegen:write` — one-shot write
- `pnpm --filter=@posthog/frontend typegen:check` — CI parity check

### Iterating on one logic — skip the full scan

Full typegen + `tsc --noEmit` over the whole codebase is slow. When you're iterating
on a single logic, scope both to that file:

```sh
# Regenerate the type for one logic
pnpm --filter=@posthog/frontend exec kea-typegen write \
    -f frontend/src/scenes/foo/fooLogic.ts -r ./frontend/src

# Type-check just that file (and its imports — fast, but won't catch downstream
# breakage in other files that consume the new types)
pnpm --filter=@posthog/frontend exec tsc --noEmit \
    frontend/src/scenes/foo/fooLogic.ts
```

Use this loop while writing the logic; run the full `typegen:check` /
`typescript:check` once at the end to confirm nothing else broke.

Never edit a `*LogicType.ts` file by hand — change the logic and re-run typegen.

For keyed logics, annotate the export explicitly:
`export const fooLogic: LogicWrapper<fooLogicType> = kea<fooLogicType>([...])`.

## When in doubt

- Read the relevant reference above before inventing a new pattern.
- Read the upstream [keajs.org](https://keajs.org) docs for builder signatures.
- Search the repo for the builder name in `*Logic.ts` — there are hundreds of working
  examples and the conventions are stable.
- For state-management decisions, favour the option that lets you delete code elsewhere.
