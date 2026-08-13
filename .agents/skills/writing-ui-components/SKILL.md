---
name: writing-ui-components
description: >
  Structure and abstraction rules for PostHog UI code — any React component or frontend file under
  `frontend/src/` or `products/*/frontend/`. Use ALWAYS before creating, moving, splitting, or
  restructuring a component or frontend file, extracting a shared/generic component, promoting a
  component to `lib/`, renaming a frontend symbol or feature, or reviewing a diff that does any of
  these. Covers file and folder organization (one component per file, one home per symbol, no
  re-export shims or barrels), when duplication becomes a component and when a generic is premature,
  rename sweeps and the frozen-strings contract (event names, properties, flag keys, `data-attr`
  values are API), UI resolution states (loading, empty, and error are three different screens), and
  visual discipline (design tokens, on-brand custom components with no AI slop, real interactive
  elements, reduced motion, Storybook).
  Component choice (Lemon vs quill) lives in `frontend/src/AGENTS.md` Rule 1; state management in
  `/writing-kea-logics`.
---

# Writing UI components

How UI code is structured: which file a component lives in, when duplication becomes a shared
component, what a rename must sweep, and what every component renders before its data resolves.
Applies to everything under `frontend/src/` and `products/*/frontend/`.

Each section leads with its gate question. If you can answer the gate honestly, the details
below it usually follow on their own.

## Use this skill when

- Creating a new component, scene, view, hook, or frontend module
- Splitting or restructuring an existing component file, or moving one between folders
- Extracting a repeated shape into a shared/generic component, or promoting one toward `lib/`
- Renaming a frontend symbol, file, or feature vocabulary
- Adding loading/empty/error handling to a view
- Reviewing a PR that does any of the above

## Companion rules (do not duplicate)

This skill owns _structure_. These own their own territory — link to them, don't restate them:

- [frontend/src/AGENTS.md](../../../frontend/src/AGENTS.md) — **Rule 1: reuse before you create**
  (the Lemon/quill lookup table) and Rule 2 (generated API types). Both apply before anything here.
- [writing-kea-logics](../writing-kea-logics/SKILL.md) — business logic lives in a logic, not in
  React; state container choice. [using-kea-disposables](../using-kea-disposables/SKILL.md) for
  anything that needs cleanup.
- [writing-user-facing-copy](../writing-user-facing-copy/SKILL.md) — every visible string.
- [writing-code-comments](../writing-code-comments/SKILL.md) — every comment, including the
  pinned-string comments below.
- [building-product-empty-states](../building-product-empty-states/SKILL.md) — scene-level
  first-run empty states (the `ProductEmptyState` gate).
- [scene-menu-bar](../scene-menu-bar/SKILL.md) — scene action surfaces.
- [setting-feature-flags-in-storybook](../setting-feature-flags-in-storybook/SKILL.md) — stories
  for flag-gated components.

## Survey precedent before you build

> **Gate: which existing scene or component are you modeling this on — and does that model
> itself follow these rules?**

Brand consistency comes from imitation, not invention. Before building any new UI, read how
2–3 comparable scenes or components are implemented — component choice, density, layout, file
structure, logic wiring, `data-attr` naming — and name the precedent you're following. A new
surface that matches its compliant neighbors is on-brand by construction.

But **filter precedent through the conventions**. The codebase carries legacy that predates
these rules — clickable divs, hand-rolled tables, new-style-banned `LemonMenu`s, deprecated
`ProductIntroduction` call sites, re-export shims, slop styling. An existing violation is
history, not license: this skill and `frontend/src/AGENTS.md` outrank precedent. When the
nearest example violates the rules, follow the rules — and if the violation is cheap to fix,
convert it while you're there ([references/anti-patterns.md](references/anti-patterns.md)).

Telling good precedent from bad:

- **Prefer reference implementations named in skills** — e.g. MCP analytics for
  [empty states](../building-product-empty-states/SKILL.md), the migrated scenes listed in
  [scene-menu-bar](../scene-menu-bar/SKILL.md) — and recently-touched code (`git log`) over
  untouched corners.
- **Prefer current primitives**: quill menus/comboboxes over `LemonMenu`/Radix menus,
  `ProductEmptyState` over `ProductIntroduction`, generated `*Api` types over handwritten ones.
- When they conflict, the priority order is **conventions > compliant precedent > invention**.
  Inventing a new pattern when a compliant precedent exists is itself a reuse violation.

## Code organization

> **Gate: can a reader find this code by name, from the folder tree alone?**

- **One component per file.** A file exports the component its name promises — nothing else. A
  private sub-piece may stay only when it is unexported, has a single consumer in the same file,
  is small (a few lines of markup, not a second real component), and is inseparable from the
  parent (mode-variants of the same export). The moment it's exported, it moves to its own file.
  Named exports only, never `default` (handbook rule).
- **One concern per file.** When a file accumulates a second concern, split it: pure decision
  functions come out of logics and components into a sibling module and get tested directly
  (see [writing-tests](../writing-tests/SKILL.md) — extract, don't escalate); a dialog opened by
  a button is not part of the button. Copy stays inline where reviewers see it in rendering
  context — extract only long-form copy blocks or copy shared across components.
- **Folders mirror the feature.** A flow is a shell plus a `steps/` folder; reusable pieces in
  `components/`; shared helpers in `utils.ts` (or the layer's existing `helpers.ts`). The tree
  should read like a table of contents. Files are named after their main export
  (`DashboardMenu.tsx`, `dashboardLogic.ts`); no `index.ts`, `styles.css`, or other generic names.
- **Every symbol has exactly one home.** No re-export shims creating a second import path, no
  `export * from`, no new barrel files. When you extract or move a module, point every consumer
  at the new home in the same PR and delete the old path — imports are mechanical; sweep them.
  The only tolerated shim is inside a multi-PR migration that crosses team ownership boundaries,
  marked `// TODO(<issue>): delete after <migration>` and removed in the final PR of the series.

## The abstraction ladder

> **Gate: does the call site read as content, not markup?**

That's the litmus for a good extraction: callers pass data and slots; the generic owns the
scaffolding. Climb the ladder one rung at a time:

1. **Reuse before you create** — [frontend/src/AGENTS.md Rule 1](../../../frontend/src/AGENTS.md).
   The design system is the brand: Lemon/quill components carry PostHog's tokens, density, and
   interaction patterns, so building from them is what keeps a scene looking like PostHog.
   Hand-rolling markup that an existing component already is counts as duplication _and_ a
   branding leak.
2. **Duplicate before you abstract.** Extract a shared component when the same shape appears
   **three times**, or **twice within one feature with a third clearly coming**. Below that
   threshold, duplication is cheaper than the wrong abstraction.
3. **The generic owns scaffolding, not variants.** If the second call site needs a boolean prop
   to switch off half the generic's behavior (`hideIcon`, `noBorder`, `variant="other"`), it is
   not the same shape — inline the call sites again or split into two components.
4. **Keep new generics feature-local.** They live next to the feature that uses them until a
   second _feature_ needs them; promotion is one `git mv` away. The path is: feature folder →
   `frontend/src/lib/components/` (app-shared) → lemon-ui / quill (design system — needs design
   review). Products never import from each other: a second consumer in another product forces
   promotion to a shared layer, not a cross-product import.
5. **Don't abstract single-consumer, state-coordinated components.** A wrapper with one caller
   is indirection, not reuse — delete the layer.

## Naming and vocabulary

> **Gate: does the name promise exactly what the thing does — and does it promise it everywhere?**

- **One vocabulary per concept.** When a feature is renamed, sweep the code symbols completely —
  components, logics, files, folders, props, test names. `git grep` the old name before calling
  the rename done; a codename surviving alongside the real name costs every future reader a
  translation step.
- **Names don't over-promise.** A hook named for "any wizard run" must not answer only for
  self-driving; a `use<X>` that only works under one scene is named for that scene. If the scope
  is narrower than the name, rename one of them.
- **Wire strings are frozen.** The rename sweep stops at anything the outside world can see:

  | Frozen string                          | Who depends on it                                              |
  | -------------------------------------- | -------------------------------------------------------------- |
  | Event names (`posthog.capture('…')`)   | dashboards, insights, cohorts, alerts                          |
  | Event/person property names and values | the same, plus breakdowns and filters                          |
  | Feature flag keys                      | rollout state lives server-side; a renamed key is a new flag   |
  | `data-attr` values                     | autocapture-built dashboards, Playwright selectors, QA tooling |
  | `localStorage` / `sessionStorage` keys | users' persisted state silently resets                         |
  | URL paths and search params            | bookmarks, docs links, `urlToAction` handlers                  |

  Pin them where they're defined with a comment stating the constraint, e.g.
  `// pinned: analytics event name — renaming breaks dashboards`. If a wire string genuinely
  must change, that's a migration (emit both, backfill, deprecate), not a rename.

## Resolution states

> **Gate: what does this component render before its data has answered?**

**Loading, empty, and error are three different screens.** "Empty" is a verdict about resolved
data; rendering it from unresolved data shows every user a flash of the wrong screen — or worse,
acts on it.

```tsx
// don't — the empty state renders during the first fetch
{
  items.length === 0 ? <EmptyState /> : <ItemsList items={items} />
}

// do — unresolved data is its own branch, checked first
{
  itemsLoading ? <Spinner /> : items.length === 0 ? <EmptyState /> : <ItemsList items={items} />
}
```

- Branch in resolution order: loading → error → empty → content.
- Model "not yet known" explicitly in the logic — `null` (a loader's natural default) or an
  explicit `'unknown'`, never `false`/`[]` doubling as "nobody asked yet". See
  [state-decision.md](../writing-kea-logics/references/state-decision.md#unknown-is-a-state) for
  the logic side.
- Scene-level first-run ("product not set up") belongs to the
  [ProductEmptyState gate](../building-product-empty-states/SKILL.md), not bespoke branching.
- Any submit that fires a network request disables the trigger and shows a loading state while
  in flight (root `CLAUDE.md` rule) — reset in both success and error paths.

## Visual discipline

- **Design tokens, not hardcoded values.** Colors come from tokens (`--color-*`, product accents
  in `frontend/src/styles/base.scss`) — a hardcoded hex is invisible to dark mode. Spacing comes
  from the Tailwind scale; an arbitrary value (`w-[347px]`) needs a comment explaining the
  constraint, or it should be a scale value.
- **Custom components stay on brand.** When the design system genuinely lacks what you need,
  build the new component from the system's primitives and tokens (colors, spacing, radii,
  typography) and match the density and tone of the surrounding scene — PostHog's product UI is
  dense, flat, and utilitarian. Do not fill the gap with the generic AI-generated look ("AI
  slop"): purple/blue gradients and neon glows, gradient text, glassmorphism and blurred orbs,
  oversized radii and decorative shadows, icon-tile-above-heading card grids, pill badges
  floating over headings, and motion that isn't tied to a state change. The test: every styling
  choice is traceable to a token or an existing PostHog pattern — if it isn't, it's a tell. Full
  catalog: [references/anti-patterns.md](references/anti-patterns.md#the-ai-slop-component).
- **Tailwind utilities over inline styles; components over repeated class strings.** A class
  string copy-pasted across three files is a component in disguise. SCSS is the fallback for
  what Tailwind can't express, namespaced BEM-style under the component's class (handbook rule).
- **Interactive elements are real elements.** A real `<button>`/`<a>` — which is what
  `LemonButton` and quill triggers render — never `onClick` on a `<div>` or a Card. Real elements
  give keyboard focus, Enter/Space activation, and autocapture for free. If the design-system
  component isn't semantically right, extend it; don't drop to a clickable div. Don't remove
  focus outlines; give motion a `motion-reduce:` variant.
- **`data-attr` on meaningful interactions.** New buttons and key interactive elements get a
  kebab-case `data-attr` (match the surrounding scene's pattern) — it's how autocapture
  dashboards and Playwright find them. Once shipped it's frozen (see the table above).
- **New presentational components ship with a story** (handbook rule) — visual-regression
  coverage is free once the story exists. Flag-gated components use the `featureFlags` story
  parameter ([setting-feature-flags-in-storybook](../setting-feature-flags-in-storybook/SKILL.md)).

## Anti-patterns

[references/anti-patterns.md](references/anti-patterns.md) is the convert-on-sight catalog —
before/after for the rules above. Read it when reviewing UI diffs.

## Before you open the PR

- [ ] New UI is modeled on named, compliant precedent — violating neighbors were not copied
- [ ] Every new file exports what its name promises — one component each, named exports
- [ ] No new re-export shims or barrels; moved symbols' consumers all updated, old paths deleted
- [ ] New generics: call sites read as content; no variant booleans; feature-local unless a
      second feature exists today
- [ ] Loading, empty, and error all reachable and distinct; empty never renders from unresolved
      data
- [ ] No hardcoded colors; arbitrary Tailwind values justified or replaced
- [ ] Renames swept (`git grep` the old name returns nothing); wire strings untouched and pinned
- [ ] New presentational component has a story
- [ ] Typecheck/lint cadence per [frontend/src/AGENTS.md](../../../frontend/src/AGENTS.md) —
      full check once at the end, `pnpm --filter=@posthog/frontend fix` before finishing
