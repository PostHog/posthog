# Dashboards Finder/grid experiment — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the A/C/B dashboards-list experiment behind a multivariate flag — this plan covers **Increment 1 only** (foundation + grid arm + the core `opened from list` event); Increments 2–5 are outlined for their own plans.

**Architecture:** A multivariate flag `dashboards-list-view` (control|grid|finder) resolves through a small registry (mirroring `authFlowVariants`) to a `DashboardsContent` switch. Control renders today's `DashboardsTableContainer` unchanged. Grid renders a new `DashboardsGrid` backed by a focused `dashboardsFileSystemLogic` that reads the dashboards subtree from the existing `projectTreeDataLogic` and delegates writes (move) back to it — `FileSystem` rows stay the single source of truth.

**Tech Stack:** TypeScript, React, kea + kea-test-utils, `@testing-library/react`, `@dnd-kit/core` (existing), PostHog frontend conventions.

## Global Constraints

- Flag key (verbatim): `dashboards-list-view`, variants `control,grid,finder`. Constant `FEATURE_FLAGS.DASHBOARDS_LIST_VIEW`.
- Resolver defaults unknown/missing/boolean/empty flag values to `control` — never to a treatment arm (EC-01a/b/c/g, EC-02d).
- Control path (`DashboardsTable`/`DashboardsTableContainer`) must stay byte-for-byte unchanged (REQ-03, EC-02c).
- Experiment is group-level on `project`; events must carry `$feature/dashboards-list-view` + the project group (REQ-24) — wiring confirmed during the measurement increment; do not regress it.
- Frontend: explicit return types; business logic in kea, not React hooks; Sentence casing for all UI copy; tailwind utilities not inline styles; use `lib/dayjs` not dayjs.
- No user-facing list/grid toggle during the experiment (REQ-07). Generic dashboard type-icon only, no thumbnails (REQ-15).
- Pinned challenge items that affect later increments: CH-01 (organized = has folders OTHER than `Unfiled`), CH-02 (cut ≠ delete), CH-03 (duplicate must not inherit sharing/subscriptions), CH-04/05 (pogo-stick definition).

---

## Increment 1 — foundation + grid arm + core metric

Covers REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-07 (held-constant chrome via reuse), REQ-13 (read + move), REQ-16.

### Task 1: Add the multivariate flag

**Files:** Modify `frontend/src/lib/constants.tsx` (in the `FEATURE_FLAGS` object, near the other `DASHBOARD_*` entries).

- [ ] **Step 1: Add the flag constant**

```tsx
DASHBOARDS_LIST_VIEW: 'dashboards-list-view', // owner: @vdekrijger #team-product-analytics multivariate=control,grid,finder — dashboards list presentation A/C/B
```

- [ ] **Step 2: Verify typecheck of constants**

Run: `pnpm --filter=@posthog/frontend exec tsc --noEmit -p tsconfig.json 2>&1 | grep constants || echo OK`
Expected: OK (no new errors from constants.tsx).

- [ ] **Step 3: Commit** — `git commit -m "feat(dashboards): add dashboards-list-view multivariate flag"`

### Task 2: Variant resolver (REQ-01, REQ-02)

**Files:**

- Create `frontend/src/scenes/dashboard/dashboards/dashboardsListViewVariants.ts`
- Test `frontend/src/scenes/dashboard/dashboards/dashboardsListViewVariants.test.ts`

**Interfaces:**

- Produces: `type DashboardsListViewVariant = 'control' | 'grid' | 'finder'`; `resolveDashboardsListViewVariant(featureFlags: FeatureFlagsSet): DashboardsListViewVariant`.

- [ ] **Step 1: Write failing tests**

```typescript
import { FEATURE_FLAGS } from 'lib/constants'
import { resolveDashboardsListViewVariant } from './dashboardsListViewVariants'

describe('resolveDashboardsListViewVariant', () => {
  it.each([
    [undefined, 'control'],
    ['', 'control'],
    ['unknown', 'control'],
    [true, 'control'],
    ['control', 'control'],
    ['grid', 'grid'],
    ['finder', 'finder'],
  ])('flag %p resolves to %p', (value, expected) => {
    expect(resolveDashboardsListViewVariant({ [FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]: value as any })).toBe(expected)
  })
})
```

- [ ] **Step 2: Run, expect fail** — `pnpm --filter=@posthog/frontend exec jest dashboardsListViewVariants` → FAIL (module not found)

- [ ] **Step 3: Implement**

```typescript
import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export type DashboardsListViewVariant = 'control' | 'grid' | 'finder'

const DEFAULT_VARIANT: DashboardsListViewVariant = 'control'

export const DASHBOARDS_LIST_VIEW_VARIANTS: DashboardsListViewVariant[] = ['control', 'grid', 'finder']

export function resolveDashboardsListViewVariant(featureFlags: FeatureFlagsSet): DashboardsListViewVariant {
  const variant = featureFlags[FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]
  return typeof variant === 'string' && (DASHBOARDS_LIST_VIEW_VARIANTS as string[]).includes(variant)
    ? (variant as DashboardsListViewVariant)
    : DEFAULT_VARIANT
}
```

- [ ] **Step 4: Run, expect pass.** **Step 5: Commit** — `feat(dashboards): add dashboards-list-view variant resolver`

### Task 3: DashboardsContent switch + wire into scene (REQ-02, REQ-03, REQ-07)

**Files:**

- Create `frontend/src/scenes/dashboard/dashboards/DashboardsContent.tsx`
- Test `frontend/src/scenes/dashboard/dashboards/DashboardsContent.test.tsx`
- Modify `frontend/src/scenes/dashboard/dashboards/Dashboards.tsx` (replace the `<DashboardsTableContainer />` render at the data branch with `<DashboardsContent />`)

**Interfaces:**

- Consumes: `resolveDashboardsListViewVariant`, `DashboardsTableContainer`, `DashboardsGrid` (Task 6 — until then map grid→DashboardsTableContainer with a TODO so the switch is testable independently).
- Produces: `DashboardsContent(): JSX.Element`.

- [ ] **Step 1: Failing test** — control renders the table; unknown flag renders the table; `grid` renders the grid container.

```tsx
import { render, screen } from '@testing-library/react'
import { useValues } from 'kea'
import { initKeaTests } from '~/test/init'
import { DashboardsContent } from './DashboardsContent'

jest.mock('./DashboardsTable', () => ({ DashboardsTableContainer: () => <div>table-arm</div> }))
jest.mock('./DashboardsGrid', () => ({ DashboardsGrid: () => <div>grid-arm</div> }))
jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn() }))

describe('DashboardsContent', () => {
  beforeEach(() => initKeaTests())
  it('renders table for control / unknown', () => {
    ;(useValues as jest.Mock).mockReturnValue({ featureFlags: {} })
    render(<DashboardsContent />)
    expect(screen.getByText('table-arm')).toBeInTheDocument()
  })
  it('renders grid for grid variant', () => {
    ;(useValues as jest.Mock).mockReturnValue({ featureFlags: { 'dashboards-list-view': 'grid' } })
    render(<DashboardsContent />)
    expect(screen.getByText('grid-arm')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement** the switch (finder → table for Increment 1, replaced in Increment 2):

```tsx
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { resolveDashboardsListViewVariant } from './dashboardsListViewVariants'
import { DashboardsTableContainer } from './DashboardsTable'
import { DashboardsGrid } from './DashboardsGrid'

export function DashboardsContent(): JSX.Element {
  const { featureFlags } = useValues(featureFlagLogic)
  const variant = resolveDashboardsListViewVariant(featureFlags)
  if (variant === 'grid') {
    return <DashboardsGrid />
  }
  // 'finder' falls back to the control table until Increment 2 ships DashboardsFinder.
  return <DashboardsTableContainer />
}
```

- [ ] **Step 4: Wire into `Dashboards.tsx`** — replace `<DashboardsTableContainer />` (the non-Templates data branch) with `<DashboardsContent />`; add the import; remove the now-unused `DashboardsTableContainer` import if no longer referenced there. Control behavior is unchanged because control renders `DashboardsTableContainer`.

- [ ] **Step 5: Run tests + targeted typecheck. Step 6: Commit** — `feat(dashboards): add variant switch for dashboards list view`

### Task 4: `dashboard opened from list` event (REQ-16)

**Files:** Modify `frontend/src/lib/utils/eventUsageLogic.ts` (add action + listener). Dispatch from the grid card open handler (Task 6) and the control row link.

**Interfaces:**

- Produces: `reportDashboardOpenedFromList({ dashboardId, variant, msSinceListLoaded, usedSearch, clicksBeforeOpen, openSource })`.

- [ ] **Step 1: Add the action** (in the `actions({...})` block):

```typescript
reportDashboardOpenedFromList: (props: {
    dashboardId: number
    variant: string
    msSinceListLoaded: number
    usedSearch: boolean
    clicksBeforeOpen: number
    openSource: 'root' | 'folder' | 'grouped' | 'search'
}) => props,
```

- [ ] **Step 2: Add the listener** (in `listeners({...})`), clamping negatives (EC-16k):

```typescript
reportDashboardOpenedFromList: async ({ dashboardId, variant, msSinceListLoaded, usedSearch, clicksBeforeOpen, openSource }) => {
    posthog.capture('dashboard opened from list', {
        dashboard_id: dashboardId,
        variant,
        ms_since_list_loaded: Math.max(0, Math.round(msSinceListLoaded)),
        used_search: usedSearch,
        clicks_before_open: clicksBeforeOpen,
        open_source: openSource,
    })
},
```

- [ ] **Step 3: Test** (kea-test-utils + posthog spy): dispatching the action calls `posthog.capture('dashboard opened from list', ...)` with clamped ms. **Step 4: Commit** — `feat(dashboards): add 'dashboard opened from list' event`

### Task 5: `dashboardsFileSystemLogic` — folder-grouped dashboards (REQ-04, REQ-13 read)

**Files:**

- Create `frontend/src/scenes/dashboard/dashboards/dashboardsFileSystemLogic.ts`
- Test `frontend/src/scenes/dashboard/dashboards/dashboardsFileSystemLogic.test.ts`

**Interfaces:**

- Consumes: `projectTreeDataLogic` values `['folders']` (FileSystem rows keyed by folder path; rows have `type`, `ref`, `path`), actions `['moveItem']`; `dashboardsLogic` value `['dashboards']`.
- Produces: selector `dashboardsByFolder: { folderPath: string; dashboards: DashboardBasicType[] }[]` (stable order), reducer `collapsedFolders: Record<string, boolean>` + action `toggleFolder(path)`, and `moveDashboardToFolder(dashboardId, folderPath)` that maps the dashboard to its `FileSystemEntry` and calls `projectTreeDataLogic.moveItem(entry, newPath, true, key)`.

- [ ] **Step 1: Failing tests** — group dashboards under their folder paths from FileSystem rows; dashboards with no folder row group under `Unfiled/Dashboards`; ordering stable; `toggleFolder` flips collapse state.

```typescript
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

describe('dashboardsFileSystemLogic', () => {
  let logic: ReturnType<typeof dashboardsFileSystemLogic.build>
  beforeEach(() => {
    initKeaTests()
    logic = dashboardsFileSystemLogic()
    logic.mount()
  })
  afterEach(() => logic.unmount())

  it('toggles folder collapse state independently', async () => {
    await expectLogic(logic, () => logic.actions.toggleFolder('Dashboards/Marketing')).toMatchValues({
      collapsedFolders: { 'Dashboards/Marketing': true },
    })
  })
})
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement** — connect to `projectTreeDataLogic` + `dashboardsLogic`; build the `dashboardsByFolder` selector by joining `dashboardsLogic.dashboards` to the FileSystem rows where `type === 'dashboard'` and `ref === String(dashboard.id)`, bucketing by the parent folder of `entry.path` (fallback `Unfiled/Dashboards`); add the `collapsedFolders` reducer + `toggleFolder`; add a `moveDashboardToFolder` listener that finds the entry and calls `projectTreeDataLogic.actions.moveItem(entry, newFolderPath + '/' + name, true, 'dashboards-grid')`.

- [ ] **Step 4: Run, expect pass. Step 5: Commit** — `feat(dashboards): add dashboardsFileSystemLogic for folder grouping`

### Task 6: `DashboardsGrid` component (REQ-04, REQ-15)

**Files:**

- Create `frontend/src/scenes/dashboard/dashboards/DashboardsGrid.tsx`
- Test `frontend/src/scenes/dashboard/dashboards/DashboardsGrid.test.tsx`

**Interfaces:**

- Consumes: `dashboardsFileSystemLogic` (`dashboardsByFolder`, `collapsedFolders`, `toggleFolder`), `dashboardsLogic` (`dashboardsLoading`), `eventUsageLogic` (`reportDashboardOpenedFromList`).

- [ ] **Step 1: Failing test** — renders a folder header per group and a card per dashboard; clicking a card navigates and fires `reportDashboardOpenedFromList` with `openSource: 'grouped'`; collapse hides cards. Use the jest/RTL pattern (initKeaTests, render, screen).

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement** — `LemonCard` grid (`grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4` via tailwind), collapsible folder headers (`IconChevronDown`, `IconFolder`), generic `IconDashboard`-style glyph per card, name + owner + last-viewed, `Link` to `/dashboard/:id`. On open, dispatch `reportDashboardOpenedFromList`. Register `grid → DashboardsGrid` (the switch in Task 3 already imports it).

- [ ] **Step 4: Run tests + targeted typecheck + jest. Step 5: Commit** — `feat(dashboards): add grid arm for dashboards list`

### Task 7: drag-to-folder in the grid (REQ-05, REQ-13 write, REQ-17)

**Files:** Modify `DashboardsGrid.tsx` (+ a `dashboard moved to folder` event in `eventUsageLogic.ts`).

- [ ] **Step 1: Failing test** — dropping a card on a folder header calls `dashboardsFileSystemLogic.moveDashboardToFolder` and fires `dashboard moved to folder` with `method: 'drag'`; a drop on the same folder is a no-op (EC-05a, EC-17e).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** with `@dnd-kit/core` (`DndContext`, `useDraggable` cards, `useDroppable` headers), reusing the `moveDashboardToFolder` listener; guard no-op (same folder) and unmount; add the `reportDashboardMovedToFolder` event. Provide a keyboard/menu move fallback (EC-05l) — the existing `…`-menu "Move to folder" already covers control; expose the same menu action on grid cards.
- [ ] **Step 4: Run tests. Step 5: Commit** — `feat(dashboards): drag-to-folder in the grid arm`

---

## Increments 2–5 (outline — each gets its own plan via writing-plans when reached)

- **Increment 2 — Finder arm:** `DashboardsFinder` + folder-first navigation state in `dashboardsFileSystemLogic` (breadcrumb, drill-in, per-tab nav), multi-select (shift-range), rename-in-place, right-click context menu. Registry maps `finder → DashboardsFinder`. Covers REQ-06, 09, 10, 11. Pin CH-06 (where "New dashboard" lands when drilled in).
- **Increment 3 — Clipboard + duplication:** cut/copy/paste buffer in the logic; paste = move (reuse `moveItem`) or duplicate (reuse `duplicateDashboard`); honor CH-02 (cut ≠ delete) and CH-03 (no silent sharing/subscription inheritance). Covers REQ-08, 12, and the `dashboards clipboard action` event (REQ-19).
- **Increment 4 — Measurement + analysis:** remaining events (`dashboard folder created|renamed|deleted` REQ-18, `dashboards view feedback` REQ-20); the first-open-success/pogo-stick guardrail derivation (REQ-21, backtestable HogQL); find-conversion (REQ-22); robust CUPED primary (REQ-23); exposure/group association tests (REQ-24); group-level randomization assertions (REQ-25); pre-exposure dashboard-count + pre-registered segments (REQ-26, 27); secondary metrics (REQ-28, 29); decision rules (REQ-30); staged rollout (REQ-31). Several are analysis/config + HogQL, not UI. **Gated on CH-09 platform validation** (group-level + winsorized/median + CUPED support).
- **Increment 5 — Feedback affordance + icons polish:** the "not a fan? tell us" affordance in non-control arms (REQ-14) and any icon refinement (REQ-15).

## Self-review

- Spec coverage: Increment 1 tasks cover REQ-01–05, 07 (reuse), 13 (read+move), 16; the rest map to Increments 2–5 above. No Increment-1 requirement is unassigned.
- Placeholder scan: code steps carry real code from the current codebase signatures; the only deferred mapping (finder→control) is explicit and labeled, not a placeholder.
- Type consistency: `DashboardsListViewVariant`, `resolveDashboardsListViewVariant`, `DashboardsContent`, `dashboardsFileSystemLogic` selectors/actions are referenced consistently across tasks.
