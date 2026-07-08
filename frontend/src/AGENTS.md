# Frontend agent guide (`frontend/src`)

Applies to any change under `frontend/src`. This is a **discovery + cadence** guide: the rules below exist because agents tend to generate before they look. The root `AGENTS.md` and the quill package guides remain authoritative — this file does not repeat them, it points at them.

## Rule 1 — Reuse before you create

**Before building any UI element, search for an existing one.** PostHog already has a badge, a label, a table, a tag, a card, a modal. Hand-rolling one with raw `<div>`/`<table>` + Tailwind is the single most common agent mistake here, and it produces unbounded, off-design output.

Where to look, in order:

1. `frontend/src/lib/lemon-ui/` — the main-app default (~50 `Lemon*` components). Grep here first.
2. `@posthog/quill` (`packages/quill/`) — preferred for menus, comboboxes, autocompletes, and new charts. Read `packages/quill/packages/primitives/AGENTS.md` for component choice **before** importing.
3. `frontend/src/lib/ui/` and `frontend/src/lib/components/` — older / app-specific shared pieces.

Common reinventions and what to use instead:

| You're about to build…               | Use instead                                                                               |
| ------------------------------------ | ----------------------------------------------------------------------------------------- |
| a `<table>`                          | `LemonTable` (`lib/lemon-ui/LemonTable`) — has sorting, pagination, loading, empty states |
| a colored status pill / count badge  | `LemonBadge`                                                                              |
| a small removable chip               | `LemonSnack` or `LemonTag`                                                                |
| a form field label                   | `LemonLabel`                                                                              |
| a dropdown / combobox / autocomplete | quill `DropdownMenu` / `Combobox` / `Autocomplete` (not a new `LemonMenu`)                |
| a card / panel                       | `LemonCard`                                                                               |
| a modal / confirm dialog             | `LemonModal` / `LemonDialog`                                                              |

If nothing fits, say so and propose extending the existing component before adding a new one. Don't silently fork.

> LemonUI vs quill, and the quill spacing/composition rules, live in the root `AGENTS.md` ("Code Style → Frontend (quill …)") and `packages/quill/packages/primitives/AGENTS.md`. Follow those — don't mix quill and Lemon inside one component's internals.

## Rule 2 — Don't handwrite API types; use the generated ones

Django serializers are the source of truth. `hogli build:openapi` generates TypeScript types (suffix `Api`) and API functions. **Never write an `interface` that mirrors a backend serializer** — import the generated type instead.

- Types: `import type { UserAuthSessionApi } from '~/generated/core/api.schemas'`
  (exemplar: `frontend/src/scenes/settings/user/loginSessionsLogic.ts`)
- Request functions: `import { getExportsContentRetrieveUrl } from '~/generated/core/api'`
  (exemplar: `frontend/src/scenes/inbox/components/signalCards/SessionReplaySignalCard.tsx`)
- Generated output lives in `frontend/src/generated/core/` and `products/*/frontend/generated/`. **These files are codegen output — never edit them by hand.** Change the serializer and rerun.

When touching `lib/api`, `api.get<`, `api.create<`, or any handwritten API interface, invoke the `/adopting-generated-api-types` skill first.

## Rule 3 — Business logic in kea, not React hooks

Covered by the root `AGENTS.md` (Code Style → Frontend). The discovery hint for this tree: if a scene/component has a `*Logic.ts`, that's where actions/reducers/selectors/listeners belong. See `/writing-kea-logics` and `/using-kea-disposables`.

## Typecheck & typegen cadence (don't over-run these)

These are slow; run them at the right moment, not after every edit.

- **TypeScript check** — `pnpm --filter=@posthog/frontend typescript:check` (runs `tsc --noEmit` over the whole app). Rely on the editor/LSP while editing; run the full check **once before you call the work done**, not per-edit.
- **kea typegen** (`*Type.ts` files) — regenerates automatically via `typegen:watch` while the dev server runs (`./bin/start` / `hogli start`). If you must regen one logic without the server, use `pnpm --filter=@posthog/frontend typegen:file <path>`. **Don't routinely run the full `typegen:write`** — it's a heavy whole-repo pass (multi-GB heap).
- **`hogli build:openapi`** — only needed when you changed a **backend serializer/viewset**. A pure `.tsx`/`.ts` change never needs it. Don't run it speculatively.

## Lint & format

Run `pnpm --filter=@posthog/frontend format` (oxlint `--fix` + oxfmt) before finishing. Config: root `.oxlintrc.json`. CSS, spelling, and copy-casing rules live in the root `AGENTS.md` (Code Style).

## Adding actions to a scene

Adding a button/toggle/action to a scene's `ScenePanel`? It must also go in that scene's `SceneMenuBar`
(create one if the scene has none). See [`layout/scenes/AGENTS.md`](./layout/scenes/AGENTS.md) and the
`/scene-menu-bar` skill.

## Deeper references

- Root `AGENTS.md` — full Code Style + architecture rules (authoritative).
- `layout/scenes/AGENTS.md` (scene action surfaces: `ScenePanel` + `SceneMenuBar` dual-write rule).
- `packages/quill/packages/primitives/AGENTS.md` — component selection matrix.
- `docs/published/handbook/engineering/conventions/frontend-coding.md` — frontend conventions.
- Skills: `/adopting-generated-api-types`, `/writing-kea-logics`, `/using-kea-disposables`, `/writing-tests`.
