# Synthetic Monitoring Frontend Implementation Progress

## Completed

### 1. Scene Types (`frontend/src/scenes/sceneTypes.ts`)
- ✅ Added `SyntheticMonitoring` and `SyntheticMonitor` to Scene enum

### 2. Type Definitions (`frontend/src/scenes/synthetic-monitoring/types.ts`)
- ✅ Created MonitorState enum
- ✅ Created SyntheticMonitor interface
- ✅ Created SyntheticMonitorCheckEvent interface
- ✅ Created SyntheticMonitoringTab enum

### 3. API Client (`frontend/src/lib/api.ts`)
- ✅ Added syntheticMonitors() and syntheticMonitor() methods to ApiRequest class
- ✅ Created api.syntheticMonitoring object with methods:
  - list(), get(id), create(data), update(id, data), delete(id)
  - pause(id), resume(id), test(id)

### 4. Logic Files
- ✅ Created `syntheticMonitoringLogic.ts` - Main list logic with:
  - Tab management
  - Monitor loading, deletion, pause/resume
  - Selectors for active/paused/failing monitors
- ✅ Created `syntheticMonitorLogic.ts` - Individual monitor logic with:
  - Form handling (kea-forms)
  - Create/update logic
  - Validation

## TODO - Components to Create

### 1. Main Scene Component
**File**: `frontend/src/scenes/synthetic-monitoring/SyntheticMonitoring.tsx`
```tsx
import { SceneContent, SceneTitleSection, SceneDivider } from '~/layout/scenes/components'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusSmall } from '@posthog/icons'

export const scene: SceneExport = {
    component: SyntheticMonitoring,
    logic: syntheticMonitoringLogic,
}

export function SyntheticMonitoring(): JSX.Element {
    // Implement similar to DataWarehouseScene or Surveys
    // - SceneTitleSection with "New monitor" button
    // - LemonTabs for Monitors/Settings tabs
    // - MonitorsTable component in monitors tab
}
```

### 2. Monitors Table Component
**File**: `frontend/src/scenes/synthetic-monitoring/components/MonitorsTable.tsx`
```tsx
import { LemonTable } from '@posthog/lemon-ui'

export function MonitorsTable(): JSX.Element {
    // Table columns:
    // - Name (with state indicator badge)
    // - URL
    // - Frequency
    // - Regions
    // - Last checked
    // - Consecutive failures
    // - Actions (test, pause/resume, edit, delete)
}
```

### 3. Monitor Form Component
**File**: `frontend/src/scenes/synthetic-monitoring/SyntheticMonitor.tsx`
```tsx
import { Form } from 'kea-forms'
import { LemonField, LemonInput, LemonSelect } from '@posthog/lemon-ui'

export const scene: SceneExport = {
    component: SyntheticMonitor,
    logic: syntheticMonitorLogic,
}

export function SyntheticMonitor({ id }: { id?: string }): JSX.Element {
    // Form fields:
    // - name, url, frequency, regions
    // - method, expected_status_code, timeout
    // - alert settings (enabled, threshold, recipients)
}
```

### 4. Monitor Detail/Results View
**File**: `frontend/src/scenes/synthetic-monitoring/components/MonitorResults.tsx`
```tsx
export function MonitorResults({ monitorId }: { monitorId: string }): JSX.Element {
    // Use HogQL query or EventsQuery to fetch synthetic_http_check events
    // Display:
    // - Status over time chart (success rate)
    // - Response time chart
    // - Recent checks table with timestamp, region, status, response time, error
}
```

### 5. URL Configuration
**File**: `frontend/src/scenes/urls.ts`

Add methods:
```ts
syntheticMonitoring: (): string => '/synthetic-monitoring'
syntheticMonitor: (id: string = 'new'): string => `/synthetic-monitoring/${id}`
```

### 6. Scene Configuration
**File**: `frontend/src/scenes/scenes.ts`

Add to sceneConfigurations:
```ts
[Scene.SyntheticMonitoring]: {
    name: 'Synthetic monitoring',
    description: 'Monitor uptime and latency of your services',
    projectBased: true,
    defaultDocsPath: '/docs/user-guides/synthetic-monitoring',
},
[Scene.SyntheticMonitor]: {
    name: 'Monitor',
    projectBased: true,
},
```

### 7. App Scenes Configuration
**File**: `frontend/src/scenes/appScenes.ts`

Add routes:
```ts
[urls.syntheticMonitoring()]: () => import('./synthetic-monitoring/SyntheticMonitoring'),
[urls.syntheticMonitor(':id')]: () => import('./synthetic-monitoring/SyntheticMonitor'),
```

## Component Structure Summary

```
frontend/src/scenes/synthetic-monitoring/
├── SyntheticMonitoring.tsx          (Main scene - list view)
├── SyntheticMonitor.tsx              (Monitor create/edit form)
├── syntheticMonitoringLogic.ts       (✅ Created)
├── syntheticMonitorLogic.ts          (✅ Created)
├── types.ts                          (✅ Created)
└── components/
    ├── MonitorsTable.tsx             (TODO - table of all monitors)
    ├── MonitorResults.tsx            (TODO - check results/charts)
    ├── MonitorStatusBadge.tsx        (TODO - colored badge for state)
    └── MonitorForm.tsx               (TODO - reusable form fields)
```

## Next Steps

1. Create URLs in `urls.ts`
2. Create main `SyntheticMonitoring.tsx` scene component
3. Create `MonitorsTable.tsx` component
4. Create `SyntheticMonitor.tsx` form scene
5. Create `MonitorResults.tsx` to display check events
6. Add scene configurations to `scenes.ts` and `appScenes.ts`
7. Run frontend formatters (`pnpm --filter=@posthog/frontend format`)
8. Test the implementation

## Key Patterns to Follow

- Use LemonUI components (LemonButton, LemonTable, LemonInput, etc.)
- Use kea for state management
- Use kea-forms for form handling
- Follow existing scene patterns (Surveys, DataWarehouse)
- Use SceneContent, SceneTitleSection, SceneDivider for layout
- Use HogQL/EventsQuery to fetch check results from events
