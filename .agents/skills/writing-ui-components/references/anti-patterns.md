# UI anti-patterns — convert on sight

Shapes that look reasonable and cause specific real problems. When you see one in code you're
writing or reviewing, convert it. Companion to [SKILL.md](../SKILL.md); the kea-side catalog
lives in
[writing-kea-logics/references/anti-patterns.md](../../writing-kea-logics/references/anti-patterns.md).

## Precedent

### "The scene next door does it" as justification

```tsx
// don't — copying a violation because a neighboring scene has one
<div className="cursor-pointer" onClick={() => actions.open()}> {/* same as FooScene */}
```

Surveying comparable scenes before building is required — imitation is how new UI stays
on-brand — but the codebase carries legacy that predates these conventions. An existing
violation is history, not license, and copying it doubles it. Conventions outrank precedent:
model on compliant, recently-touched code and the reference implementations named in skills,
and if the neighboring violation is cheap to fix, convert it while you're there.

## Files and exports

### A second exported component in the same file

```tsx
// don't — UserSettings.tsx
export function UserSettings(): JSX.Element { ... }
export function ChangePasswordDialog(): JSX.Element { ... }
```

The file's name promises `UserSettings`; nobody will find the dialog here, and the next person
adds their own copy somewhere else. Move it to `ChangePasswordDialog.tsx`. An unexported,
single-consumer, few-line sub-piece (a row chip, mode-variants of the same export) may stay.

### A re-export shim left behind after a move

```ts
// don't — old file kept "for compatibility"
export { UserBadge } from 'lib/components/UserBadge/UserBadge'
```

Now the symbol has two import paths, half the codebase uses each, and go-to-definition lands in
a stub. Point every consumer at the new home in the same PR and delete the shim — imports are
mechanical. Exception: a `// TODO(<issue>): delete after <migration>` shim inside a multi-PR
migration crossing team boundaries, removed in the final PR.

### A new `index.ts` barrel

```ts
// don't — components/index.ts
export * from './PlanCard'
export * from './ChecklistRow'
```

Barrels create a second import path for every symbol and hide what a module actually depends
on. Import from the module directly. (The handbook also bans `index.ts` as a file name outright.)

### A component defined inside a component

```tsx
// don't
function Dashboard(): JSX.Element {
  function TileHeader({ title }: { title: string }): JSX.Element { ... } // new identity every render
  return <>{tiles.map((t) => <TileHeader title={t.title} />)}</>
}
```

The inner function is a new component type on every render — React unmounts and remounts the
subtree, losing state and focus. Hoist it to the top of the file; if it's exported or grows,
it gets its own file.

### Pure decisions trapped inside a component or logic

```tsx
// don't — 40 lines of branching inline in the render (or in a listener)
const mode = flag && !skipped && (hasData || force) ? 'resume' : sawIntro ? 'browse' : 'setup'
```

Extract `computeOnboardingMode(...)` into a sibling module and test it directly — cheaper test,
better-factored code ([writing-tests](../../writing-tests/SKILL.md): extract, don't escalate).

## Abstraction

### A generic grown variant booleans

```tsx
// don't — the second caller opted out of half the component
<ChecklistRow item={item} hideIcon noBorder compact statusOnRight />
```

If a caller needs to switch off half the scaffolding, it was never the same shape. Inline the
call sites again, or split into two components that each own their scaffolding. The test for a
good generic: the call site reads as content (data + slots), not configuration.

### A wrapper with one caller

```tsx
// don't
export function InboxPanelContainer(props: InboxPanelProps): JSX.Element {
  return <InboxPanel {...props} />
}
```

Indirection, not reuse — and state coordination through the extra layer only gets worse. Delete
the layer; extract when the second real consumer exists.

### The same class string copy-pasted across files

```tsx
// don't — the third file containing this exact string
<div className="flex items-center gap-2 rounded border p-2 text-muted hover:bg-surface-hover">
```

A repeated class string is a component in disguise — the next tweak will miss one copy. Extract
the component (feature-local first, per the ladder in [SKILL.md](../SKILL.md)).

### Hand-rolled markup a design-system component already is

A raw `<table>`, a colored status `<span>`, a hand-built modal — this is the most common agent
mistake and it produces off-design output. The lookup table lives in
[frontend/src/AGENTS.md Rule 1](../../../../frontend/src/AGENTS.md); check it before writing markup.

### Speculative promotion to `lib/`

A component built for one feature but parked in `frontend/src/lib/components/` "because someone
might need it" is shared-namespace clutter with feature-shaped props. Keep it next to the
feature; promotion is one `git mv` when the second feature actually shows up.

## Semantics and visual

### `onClick` on a `<div>` (or a Card)

```tsx
// don't
<div className="cursor-pointer" onClick={() => actions.openItem(item.id)}>

// do — a real button (LemonButton renders one)
<LemonButton onClick={() => actions.openItem(item.id)}>...</LemonButton>
```

A clickable div has no keyboard focus, no Enter/Space activation, and is invisible to
autocapture. If the design calls for a clickable card, wrap or extend the system component —
don't drop to a div.

### Hardcoded colors

```tsx
// don't
<span style={{ color: '#f54e00' }}>
// don't
<span className="text-[#f54e00]">
```

Invisible to dark mode and off-palette the next time design shifts a token. Use the token
(`text-danger`, `--color-*` vars, product accents from `frontend/src/styles/base.scss`).

### Unjustified arbitrary Tailwind values

```tsx
// don't
<div className="w-[347px] mt-[13px]">
```

Magic numbers off the spacing scale. Use scale values; if a real constraint forces an arbitrary
value (aligning to an embedded iframe, a chart's fixed gutter), say so in a comment.

### Animation without a reduced-motion variant

```tsx
// don't
<div className="animate-bounce">
// do
<div className="animate-bounce motion-reduce:animate-none">
```

`prefers-reduced-motion` is an accessibility setting, not a preference to override.

### The AI-slop component

A custom component that fills a design-system gap with the statistical average of every
Tailwind tutorial instead of PostHog's brand. The tells cluster:

- **Color:** purple/blue gradients, cyan-on-dark, gradient text, neon glows, radial halo
  backgrounds. PostHog's palette comes from tokens — if a color isn't a token, it isn't ours.
- **Surfaces:** glassmorphism/`backdrop-blur` as decoration, blurred gradient orbs, cards
  nested inside cards, a thick colored stripe down one side of a rounded card, hairline border
  plus a wide soft shadow, corners rounded into blobs.
- **Layout:** the icon-tile-above-heading three-card feature grid, pill badges floating above a
  centered heading, big-number hero metrics with tiny labels, identical even spacing everywhere
  (vary rhythm: tight within groups, generous between sections).
- **Motion:** entrance animations and bounce easing for their own sake, pulsing status dots on
  static data, hover-scale on images — motion that isn't tied to a state change.

None of these are banned for being ugly; they're banned because nobody _decided_ them — they're
what generated UI converges on without constraints. The fix is constraint, not taste: build
from Lemon/quill primitives and design tokens, match the density and flatness of the
surrounding scene (PostHog product UI is dense and utilitarian), and make every styling choice
traceable to a token or an existing PostHog pattern. The copy equivalent — hype words, punchy
antithesis, em-dash addiction — is already covered by
[writing-user-facing-copy](../../writing-user-facing-copy/SKILL.md).

## Resolution states

### Empty state derived from unresolved data

```tsx
// don't — flashes "No results" during the first fetch
{
  items.length === 0 ? <EmptyState /> : <ItemsList items={items} />
}

// do — branch in resolution order: loading → error → empty → content
{
  itemsLoading ? <Spinner /> : items.length === 0 ? <EmptyState /> : <ItemsList items={items} />
}
```

### A boolean that means both "no" and "not yet"

```tsx
// don't — renders the upsell before the access check resolves
const { hasAccess } = useValues(accessLogic) // defaults to false
return hasAccess ? <Feature /> : <UpsellBanner />
```

Unknown is a state. Default to `null` and branch on resolution first — the logic side lives in
[state-decision.md](../../writing-kea-logics/references/state-decision.md#unknown-is-a-state).

## Naming and strings

### A codename surviving alongside the real name

```ts
// don't — feature shipped as "Autopilot", half the symbols still say projectX
projectXLogic.ts, useProjectXStatus, <ProjectXBanner />
```

Sweep renames completely — components, logics, files, props, test names — and `git grep` the
old name before calling it done. Every surviving alias costs future readers a translation step.

### Renaming a wire string during a refactor

```ts
// don't — this "rename" breaks every dashboard querying the old name
posthog.capture('autopilot run started') // was: 'project x run started'
```

Event names, property names/values, flag keys, `data-attr` values, storage keys, and URL paths
are frozen API (see the table in [SKILL.md](../SKILL.md#naming-and-vocabulary)). Leave them
pinned with a comment; a genuine change is a migration (emit both, backfill, deprecate), not a
rename.

### A strings module for a handful of labels

```ts
// don't — strings.ts holding two button labels
export const SAVE_LABEL = 'Save view'
export const CANCEL_LABEL = 'Cancel'
```

Short copy stays inline where reviewers see it in rendering context (and where
[writing-user-facing-copy](../../writing-user-facing-copy/SKILL.md) reviews it). Extract only
long-form copy blocks or copy genuinely shared across components.
