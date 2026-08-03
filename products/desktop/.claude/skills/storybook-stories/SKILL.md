---
name: storybook-stories
description: Write Storybook stories for PostHog UI components. Covers the provider stack stories run inside, the key gotcha that tRPC/useHostTRPC queries never resolve in Storybook (so data-fetching components render empty), and the pure-presentational split that makes a component storyable. Use when adding or fixing a *.stories.tsx file under packages/ui.
---

# Storybook stories in PostHog

Stories live next to components as `*.stories.tsx` and are collected by
`apps/code/.storybook/main.ts` (its glob includes
`packages/ui/src/**/*.stories.tsx`). Run/build:

```bash
pnpm --filter code storybook        # dev server on :6006
pnpm --filter code build-storybook  # static build (also a good CI/typecheck gate)
```

## Every story is already wrapped (don't re-wrap)

`apps/code/.storybook/preview.tsx` applies two global decorators, so a story
should **not** add its own providers or `<Theme>`:

- `withAppProviders` — a QueryClient, the host tRPC context, a DI
  `ServiceProvider`, and a minimal TanStack Router. So `useHostTRPC()`,
  `useService()`, `useRouterState()`, etc. render instead of throwing
  "must be used within a Provider".
- A `<Theme>` (Radix) bound to the dark/light toolbar global.

Add a per-story decorator only to constrain layout (e.g. wrap in a
`maxWidth` div so a full-width component sizes realistically).

## The gotcha: data never arrives in Storybook

This is the thing that wastes time. In `withAppProviders` the tRPC `ipcLink` is
a **no-op** (`apps/code/.storybook/mocks/electron-trpc.ts`), so:

- Any query issued through `useHostTRPC()` (and hooks built on it, like
  `useClaudeCliSessions`) **stays pending forever** — `query.data` is
  `undefined`, permanently.
- `useService(TOKEN)` returns an **inert proxy stub** for anything not
  explicitly bound (`service.foo().bar` never throws, but calls are no-ops).
  Only a few tokens resolve for real: `HOST_TRPC_CLIENT` (a no-op client with a
  handful of stubbed methods), `IMPERATIVE_QUERY_CLIENT`, `DIFF_WORKER_FACTORY`.

So a component that fetches its own data renders its **empty/loading** branch in
Storybook — frequently `null`. Storying it directly shows nothing.

## The fix: split a pure presentational component

Separate the data/wiring from the rendering, and story the pure part — which
also satisfies the repo rule "components render; hooks wrap exactly one query"
(`AGENTS.md`). Keep both in the same file:

```tsx
// Pure — takes data + handlers as props. This is what the story targets.
export function WidgetList({ items, onPick }: WidgetListProps) { … }

// Container — does the tRPC/useService wiring, renders <WidgetList/>.
export function Widget({ repoPath }: WidgetProps) {
  const { data } = useSomeQuery(repoPath);
  return <WidgetList items={data?.items ?? []} onPick={…} />;
}
```

Then each story is just `args` for `WidgetList` — one per visual state (empty,
single, over-limit, in-flight/disabled, fallback text, …). Real example:
`packages/ui/src/features/task-detail/components/ContinueCliSessions.tsx` +
`.stories.tsx`.

Filtering/branching that lives in the container (not the pure view) isn't
exercised by these visual stories — cover it with a small unit test if it's
worth pinning.

## Conventions

- `title` groups in the sidebar, e.g. `"Task Detail/ContinueCliSessions"`.
- Build fixtures with a small factory (`session(overrides)`) rather than
  repeating object literals across stories.
- `Date.now()`/`new Date()` are fine in stories, but fixed ISO strings keep
  relative-time output stable enough for visual review.
- Typecheck covers stories (they're `.tsx` under the package); a
  `build-storybook` additionally catches Storybook-specific breakage.
