---
paths:
  - 'frontend/src/**'
  - 'products/*/frontend/**'
  - 'packages/quill/**'
---

For any frontend work — the main app (`frontend/src/`) **or** a product frontend (`products/*/frontend/`) — follow [frontend/src/AGENTS.md](../../frontend/src/AGENTS.md): reuse existing Lemon/quill components instead of hand-rolling tables/badges/labels, import generated `*Api` types instead of handwriting them, and run typecheck/typegen at the right moments.
Product frontends share the same components and generated types, so the same rules apply there.

Quill design system: before writing UI that imports `@posthog/quill` / `lib/ui/quill`, read [packages/quill/packages/primitives/AGENTS.md](../../packages/quill/packages/primitives/AGENTS.md) — component choice (dropdown vs select vs combobox, accordion vs collapsible, etc.), composition, and spacing rules.
Charts: [packages/quill/packages/charts/AGENTS.md](../../packages/quill/packages/charts/AGENTS.md); DataTable/DateTimePicker: [packages/quill/packages/components/AGENTS.md](../../packages/quill/packages/components/AGENTS.md)

Quill vs LemonUI: LemonUI is the default in the main app.
Use quill for menus, comboboxes, and autocompletes (`DropdownMenu`, `Combobox`, `Autocomplete` from `@posthog/quill`), with the trigger styled to match the surrounding scene's existing UI (LemonButton / ButtonPrimitive).
Don't add new `LemonMenu` or `lib/ui/DropdownMenu` (Radix) menus — those are legacy.
Don't mix quill and Lemon components within one component's internals.
Quill uses Base UI's `render` prop, not Radix's `asChild` — don't carry `asChild` over when converting.
