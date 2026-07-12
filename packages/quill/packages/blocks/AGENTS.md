# Blocks — Agent Reference

`@posthog/quill-blocks` is the product-level patterns layer of quill (tokens > primitives > components > blocks): opinionated, product-shaped compositions that stay consistent across every PostHog surface.
Import from `@posthog/quill` (the aggregate), not from this package directly.

Layering check before adding here: reusable UI built only on Base UI belongs in `primitives`; compositions of primitives with internal wiring (state machines, data plumbing) belong in `components`; blocks are for full product patterns (a filter, a page header, a command palette) that a product drops in wholesale.

## Catalog

| Block             | Use for                                                                               |
| ----------------- | ------------------------------------------------------------------------------------- |
| `DateRangeFilter` | A date filter button: preset list with instant apply, calendar range picker on demand |

## DateRangeFilter

Presets-first date filter. The trigger opens a vertical quick-range list; selecting a preset applies immediately and closes. An optional "Custom range…" row swaps in `DateTimePicker` as a pure calendar (`ranges={[]}`), which applies concrete `Date`s.

Rules:

- **The block never interprets preset meaning.** Each preset carries an opaque `value` payload returned verbatim through `onPresetSelect(preset)`. Persistence vocabulary (e.g. PostHog's relative date strings like `-7d`) belongs to the host, never here.
- `onCustomApply(start, end)` receives concrete browser-local `Date`s — hosts that need timezone-resolved or rolling semantics must convert on their side.
- `customActive` marks the current value as a custom range: the row highlights and the popover opens straight to the calendar (seeded from `customStart`/`customEnd`).
- `previewStart`/`previewEnd` on a preset only seed the calendar preview; they are not the source of truth for what the preset means.
- `listFooter` pins host content below the preset list (shown in the list view only). Use it for host-specific controls; don't add host concepts as block props.
- `trigger` overrides the default outline button when the host needs its own chrome (icons, data-attrs, skins).
- Day-granular by default; pass `showTime` for time-of-day entry.

```tsx
<DateRangeFilter
  label="Last 7 days"
  presets={[{ id: '7d', label: 'Last 7 days', value: '-7d', previewStart: (now) => subDays(now, 7) }]}
  selectedPresetId="7d"
  onPresetSelect={(preset) => persist(preset.value)}
  onCustomApply={(start, end) => persistConcrete(start, end)}
  customActive={isCustom}
  listFooter={<MyExtraControls />}
/>
```

## Conventions

Same as the other packages: Tailwind utilities only, semantic tokens, `data-slot` on structural elements, stories co-located (`*.stories.tsx`), jest tests co-located (`*.test.tsx`, run via the frontend jest project). Update this file's catalog and rules in the same PR as any block change — a lint-staged warning fires otherwise.
