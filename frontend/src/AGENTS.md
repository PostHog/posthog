# Frontend agent guide (`frontend/src`)

Applies to any change under `frontend/src`. This is a **discovery + cadence** guide: the rules below exist because agents tend to generate before they look. The root `AGENTS.md` and the quill package guides remain authoritative — this file does not repeat them, it points at them.

## Rule 1 — Reuse before you create

**Before building any UI element, search for an existing one.** PostHog already has a badge, a label, a table, a tag, a card, a modal. Hand-rolling one with raw `<div>`/`<table>` + Tailwind is the single most common agent mistake here, and it produces unbounded, off-design output. Reuse is also how the product stays on-brand: Lemon/quill components carry PostHog's tokens, density, and interaction patterns, so a scene built from them looks like PostHog without anyone having to think about it.

Where to look, in order:

1. `frontend/src/lib/lemon-ui/` — the main-app default (~50 `Lemon*` components). Grep here first, and in most cases stop here.
2. `frontend/src/lib/ui/` and `frontend/src/lib/components/` — older / app-specific shared pieces.

`@posthog/quill` is **not** for this tree. It targets MCP apps and the desktop app, it's deliberately more compact than LemonUI, and the main app isn't being migrated onto it, so quill components read as out of place here. A handful of files already import it; treat those as exceptions rather than a pattern to copy.

Common reinventions and what to use instead:

| You're about to build…              | Use instead                                                                               |
| ----------------------------------- | ----------------------------------------------------------------------------------------- |
| a `<table>`                         | `LemonTable` (`lib/lemon-ui/LemonTable`) — has sorting, pagination, loading, empty states |
| a colored status pill / count badge | `LemonBadge`                                                                              |
| a small removable chip              | `LemonSnack` or `LemonTag`                                                                |
| a form field label                  | `LemonLabel`                                                                              |
| a dropdown menu of actions          | `LemonMenu` with a `LemonButton` trigger (not a new `lib/ui/DropdownMenu`)                |
| a select / combobox / autocomplete  | `LemonSelect`, `LemonInputSelect`                                                         |
| a card / panel                      | `LemonCard`                                                                               |
| a modal / confirm dialog            | `LemonModal` / `LemonDialog`                                                              |

If nothing fits, say so and propose extending the existing component before adding a new one. Don't silently fork. If you do end up building custom, stay on brand: system tokens and primitives only, matching the surrounding scene's density and flatness — and none of the generic AI-generated look (purple/blue gradients, glassmorphism, gradient text, icon-tile card grids, decorative motion). The full slop-tell catalog is in the `/writing-ui-components` skill.

The same goes for patterns, not just components: before building a new scene or view, read 2–3 comparable ones and model yours on those that follow these rules. Precedent that violates Rule 5 or `/writing-ui-components` is legacy to route around, not license to repeat — conventions outrank precedent, and compliant precedent outranks invention.

> LemonUI vs quill lives in the root `AGENTS.md` ("Code Style → Frontend (quill vs LemonUI)"). If you're working somewhere quill genuinely applies (an MCP app, the desktop app), `packages/quill/packages/primitives/AGENTS.md` has its component-choice and spacing rules, and the two libraries must not be mixed inside one component's internals.

## Rule 2 — A product's UI goes in `products/<name>/frontend/`

`frontend/src/scenes/<name>/` is not the default home for product UI, and an existing folder there is not evidence that new files belong in it — about 18 products currently have UI in both trees. App-level scenes (`settings`, `onboarding`, `billing`, `max`) do legitimately live here.

Before adding a file or a directory under `scenes/`, check where that product stands:

```sh
python3 .agents/skills/placing-product-frontend-code/scripts/scene_product_split.py <scene-dir>
```

Invoke `/placing-product-frontend-code` for the decision table and for why the path matters — it drives merge-queue lane assignment, and a change anywhere under `frontend/` serializes against every other frontend PR.

## Rule 3 — Don't handwrite API types; use the generated ones

Django serializers are the source of truth. `hogli build:openapi` generates TypeScript types (suffix `Api`) and API functions. **Never write an `interface` that mirrors a backend serializer** — import the generated type instead.

- Types: `import type { UserAuthSessionApi } from '~/generated/core/api.schemas'`
  (exemplar: `frontend/src/scenes/settings/user/loginSessionsLogic.ts`)
- Request functions: `import { getExportsContentRetrieveUrl } from '~/generated/core/api'`
  (exemplar: `products/signals/frontend/inbox/components/signalCards/ScannerFindingSignalCard.tsx`)
- Generated output lives in `frontend/src/generated/core/` and `products/*/frontend/generated/`. **These files are codegen output — never edit them by hand.** Change the serializer and rerun.

When touching `lib/api`, `api.get<`, `api.create<`, or any handwritten API interface, invoke the `/adopting-generated-api-types` skill first.

## Rule 4 — Business logic in kea, not React hooks

Covered by the root `AGENTS.md` (Code Style → Frontend). The discovery hint for this tree: if a scene/component has a `*Logic.ts`, that's where actions/reducers/selectors/listeners belong. See `/writing-kea-logics` and `/using-kea-disposables`.

## Rule 5 — Structure and abstraction

Full doctrine + convert-on-sight catalog: the `/writing-ui-components` skill. Load it before creating, moving, splitting, or restructuring any component or frontend file, extracting a shared component, or renaming frontend symbols. The always-on core:

- **One component per file**, named after its export; named exports only. Every symbol has exactly one import path — no re-export shims, no new `index.ts` barrels; moving a symbol means updating every consumer in the same PR.
- **Extract a shared component when call sites read as content, not markup** — at three occurrences, or two in one feature with a third clearly coming. If the generic needs a boolean to switch off half its behavior for one caller, it isn't one shape: leave the duplication. Keep new generics feature-local until a second feature needs them (promote via `lib/components/`; never import across `products/*`).
- **Interactive elements are real `<button>`/`<a>`** — that's what `LemonButton`/quill triggers render. Never `onClick` on a `<div>`/Card.
- **Loading, empty, and error are three different screens.** Never derive "empty" from data that hasn't resolved — branch on the loading/unknown state first.
- **Renames sweep code symbols completely; wire strings stay frozen.** Event names, property names/values, flag keys, `data-attr` values, storage keys, and URL paths are API (dashboards, rollouts, and Playwright depend on them) — pin them with a comment instead of renaming.

## Rule 6 — A narrow scene is normal; a phone is not

Every surface a person reads has to hold up in a narrow scene.
The width a component gets is not the window width: the nav sidebar takes ~215px, an open side panel ~512px more, and the scene pads 32px on top.
So a 1280px window with the side panel open leaves a scene about 520px wide — narrower than a `md:` breakpoint ever fires at.
That is a normal working setup, not an edge case, and it is the case agents skip.

- **Break on the container, not the viewport.** `md:`/`lg:`/`xl:` track the window, so they fire long after the real space ran out. Container queries track the space the component actually has. `layout/navigation-3000/Navigation.tsx` names `main-content` and `main-content-container`, so `@min-[48rem]/main-content:` follows the main column. A shared component declares its own container instead, because it must respond wherever a caller places it — `lib/lemon-ui/LemonBanner/LemonBanner.tsx` is the pattern.
- **Nothing clips and nothing scrolls sideways.** Rows of buttons, tags, or chips get `flex-wrap`. Long strings truncate. Side-by-side halves stack. An unwrapped action row is the most common miss.
- **Cut decoration before content.** When something has to go at a narrow width, drop the illustration or the padding, not the explanation or the primary action.
- **Do not build for mobile.** No phone-width layouts, no touch-sized targets, no `sm:` variants for a viewport nobody runs the app at. "Narrow" means a docked panel on a laptop.
- **Look at it, don't reason about it.** Render the surface at a few widths before calling the work done. A story with a pinned container width snapshots the narrow case, so a regression shows up in visual review.

## Typecheck & typegen cadence (don't over-run these)

These are slow; run them at the right moment, not after every edit.

- **TypeScript check** — `pnpm --filter=@posthog/frontend typescript:check` (runs `tsgo --noEmit` over the whole app). Rely on the editor/LSP while editing; run the full check **once before you call the work done**, not per-edit.
- **kea typegen** (inline types) — regenerates automatically via `typegen:watch` while the dev server runs (`./bin/start` / `hogli start`). If you must regen one logic without the server, use `pnpm --filter=@posthog/frontend typegen:file <path>`. **Don't routinely run the full `typegen:write`** — it's a heavy whole-repo pass (multi-GB heap).
  All logic files use **inline types** by default: a generated `MakeLogicType` block sits above each `kea()` call, marked "Generated by kea-typegen". Agents may update those blocks (typegen reconciles them anyway); humans should let the typegen commands keep them updated. Connected values/actions carry a `// sourceLogic` comment and sort first, grouped by source logic.
- **`hogli build:openapi`** — only needed when you changed a **backend serializer/viewset**. A pure `.tsx`/`.ts` change never needs it. Don't run it speculatively.

## Lint & format

Run `pnpm --filter=@posthog/frontend fix` before finishing. It applies safe Oxlint fixes, never suggestion fixes, and always runs Oxfmt; it fails if either tool fails. `format` runs Oxfmt only, while `lint` and `format:check` only verify. Config: root `.oxlintrc.json`. CSS, spelling, and copy-casing rules live in the root `AGENTS.md` (Code Style).

## Adding actions to a scene

Adding a button/toggle/action to a scene's `ScenePanel`? It must also go in that scene's `SceneMenuBar`
(create one if the scene has none). See [`layout/scenes/AGENTS.md`](./layout/scenes/AGENTS.md) and the
`/scene-menu-bar` skill.

## Deeper references

- Root `AGENTS.md` — full Code Style + architecture rules (authoritative).
- `layout/scenes/AGENTS.md` (scene action surfaces: `ScenePanel` + `SceneMenuBar` dual-write rule).
- `packages/quill/packages/primitives/AGENTS.md` — component selection matrix.
- `docs/published/handbook/engineering/conventions/frontend-coding.md` — frontend conventions.
- Skills: `/writing-ui-components`, `/placing-product-frontend-code`, `/adopting-generated-api-types`, `/writing-kea-logics`, `/using-kea-disposables`, `/writing-tests`.
