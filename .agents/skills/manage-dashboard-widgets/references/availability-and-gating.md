# Widget availability and gating

Project setup prerequisites (exception autocapture, session recording ingestion, etc.) — **not** RBAC. Product access (`productAccess`) is separate: it gates who can see widget data via `run_widgets` and locked tiles; availability gates whether the project is configured to produce data.

## Product rule: gate at render, never at add

Users **always** pick and add widgets in `AddWidgetModal` — no filtering, disabling, or hiding catalog entries based on availability.

When a prerequisite is unmet, the **dashboard tile body** shows setup UI instead of widget content. The tile still exists (header, layout, edit/remove menus work).

Do **not**:

- Hide or disable variants in the add-widget picker
- Block `POST .../widgets/batch/` or dashboard PATCH add paths
- Show availability checks only in the edit modal

## Two patterns (pick one per widget type)

| Pattern                     | When                                                          | Catalog `availability`      | Tile render                                                                                |
| --------------------------- | ------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------ |
| **Catalog-driven guard**    | Single team flag checkable in `widgetAvailability.ts`         | Required                    | `WidgetRuntimeAvailabilityGuard` wraps `Component` (always wired in `DashboardWidgetItem`) |
| **Widget-layer setup gate** | Richer rules (multi-signal, ingestion polling, product logic) | **Omit** — guard is a no-op | Inline in widget `Component` (private gate + setup UI)                                     |

Do not set catalog `availability` when the widget handles setup internally — the guard would use the wrong (simpler) check and double-gate.

Error tracking uses inline setup gating in `ErrorTrackingWidget.tsx` — checks `exceptionIngestionLogic` (events received **or** autocapture enabled), not just `autocapture_exceptions_opt_in`.

## Catalog `availability` shape

File: `products/dashboards/frontend/widget_types/catalog.ts`

```typescript
availability?: {
    requirement: WidgetAvailabilityRequirementId  // e.g. 'exception_autocapture'
    unavailableTitle: string
    unavailableReason: string
    setupActionLabel: string
    docsHref?: string
}
```

Types and evaluators: `products/dashboards/frontend/widget_types/widgetAvailability.ts`

- `WidgetAvailabilityRequirementId` — extend here when adding a new generic requirement
- `isWidgetAvailabilityRequirementMet(requirement, team)` — exhaustive switch on team fields
- `getWidgetAvailabilityStatus(config, team)` / `useWidgetAvailability(config)` — `{ isAvailable, config }`

No `availability` key → guard renders children unchanged.

## Backend `availability_requirements` (MCP catalog)

File: `products/dashboards/backend/widget_catalog.py`

Each `WIDGET_CATALOG` entry includes **`availability_requirements`**: string ids agents see via `dashboard-widget-catalog-list` (e.g. `["session_replay_enabled"]`, `["exception_autocapture"]`).

- Set these even when FE **omits** catalog `availability` and the widget uses **inline setup gating** in its `Component` (`error_tracking_list` does both).
- FE catalog `availability.requirement` and BE `availability_requirements[0]` should use the same id when both are present.

## `WidgetRuntimeAvailabilityGuard` flow

File: `products/dashboards/frontend/components/WidgetRuntimeAvailabilityGuard/WidgetRuntimeAvailabilityGuard.tsx`

Always wraps the widget `Component` in `DashboardWidgetItem`:

```text
catalogEntry.availability
  → useWidgetAvailability()
  → isAvailable? render children (widget Component)
  → else render unavailableContentFallback ?? WidgetAvailabilitySetupPrompt
```

Props:

- `availability` — from `getDashboardWidgetCatalogEntry(widget_type)?.availability`
- `unavailableContentFallback` — optional override from `DashboardWidgetDefinition.unavailableContentFallback`
- `children` — widget `Component`

Default setup UI: `WidgetAvailabilitySetupPrompt` — generic `WidgetCardProductIntroduction` + CTA per `requirement` (admin-gated enable actions, docs link, product intent capture). Extend its `switch (availability.requirement)` when adding a new `WidgetAvailabilityRequirementId`.

## Widget-layer setup gate

When catalog `availability` is omitted, handle setup gating inside the widget `Component` as private subcomponents (e.g. `ErrorTrackingWidgetSetupGate` in `ErrorTrackingWidget.tsx`).

**Do not** modify product `SetupPrompt`, `ProductIntroduction`, or other shared lib components for widget layout. Reuse product **logic** (e.g. `exceptionIngestionLogic`) from the widget wrapper; compose `WidgetCardProductIntroduction` for tile-friendly setup UI.

## Error tracking reference implementation

| Piece                           | Path                                                                         | Role                                                                         |
| ------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Widget                          | `widgets/error_tracking/ErrorTrackingWidget.tsx`                             | Setup gate + body + empty/loading states                                     |
| Product prompt (reference only) | `products/error_tracking/frontend/components/SetupPrompt/SetupPrompt.tsx`    | Standalone product surface — **do not import or extend for dashboard tiles** |
| Generic prompt (catalog guard)  | `components/WidgetAvailabilitySetupPrompt/WidgetAvailabilitySetupPrompt.tsx` | Catalog-driven enable-exception-autocapture UI                               |
| Widget tile layout wrapper      | `components/WidgetCardProductIntroduction/WidgetCardProductIntroduction.tsx` | Container-query responsive layout for setup prompts inside `WidgetCardBody`  |

Loading state renders **outside** the setup wrapper so skeletons show while fetching.

## Adding a new generic requirement

1. Add id to `WidgetAvailabilityRequirementId` in `widgetAvailability.ts`
2. Implement check in `isWidgetAvailabilityRequirementMet` (team field or helper)
3. Add UI branch in `WidgetAvailabilitySetupPrompt` (enable action, docs, intents)
4. Set `availability` on catalog entry
5. Test: `widgetAvailability.test.ts`, `WidgetRuntimeAvailabilityGuard.test.tsx`

## Checklist: widget type needs setup gating

- [ ] **Simple team flag?** Set catalog `availability` + evaluator in `widgetAvailability.ts` + prompt branch in `WidgetAvailabilitySetupPrompt`. Optional `unavailableContentFallback` on registry for custom setup UI.
- [ ] **Richer product rules?** Omit catalog `availability`; add private setup gate + prompt UI inside `widgets/<product>/<Component>.tsx` (reuse product logic; do not modify product SetupPrompt)
- [ ] Confirm add modal still lists the widget unconditionally
- [ ] Setup UI replaces tile **body** only — header/menus unchanged
- [ ] Loading skeleton bypasses setup prompt
- [ ] Admin restriction on destructive enable actions (`useRestrictedArea`)
- [ ] Tests for met/unmet requirement at render time

See also: [checklist-new-widget-type.md](checklist-new-widget-type.md) §4 (catalog `availability` bullet), [composition.md](composition.md) (loading ownership).
