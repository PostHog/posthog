# Repo patterns

Use these files as the canonical local examples.

## Fully tab aware

### `insightSceneLogic`

Files:

- `frontend/src/scenes/insights/InsightScene.tsx`
- `frontend/src/scenes/insights/insightSceneLogic.tsx`
- `frontend/src/scenes/insights/InsightAsScene.tsx`

Why it is the best general example:

- Root scene logic uses `tabAwareScene()`
- Scene component requires `tabId`
- Route params and search params are owned by the scene root via `tabAwareUrlToAction` and `tabAwareActionToUrl`
- Heavy child logics are attached with `useAttachedLogic`
- The scene root stays mounted while child React components remount

Key lesson:

- Keep route ownership in the scene root.
- Keep resource/editor logic attached under that root.

### `dashboardsLogic`

Files:

- `frontend/src/scenes/dashboard/dashboards/dashboardsLogic.ts`
- `frontend/src/scenes/dashboard/dashboards/dashboardsLogic.test.ts`

Why it matters:

- Simple list scene with tab-aware query-param sync
- Good example of scene-owned filters and scene-owned URL params
- Good test fixture for mounting a tab-aware scene logic with `tabId`

### `endpointSceneLogic`

Files:

- `products/endpoints/frontend/endpointSceneLogic.tsx`
- `products/endpoints/frontend/endpointSceneLogic.test.ts`
- `frontend/src/lib/logic/scenes/tabSceneUtils.ts`

Why it matters:

- Strong example of inactive-tab URL updates
- Uses `getTabSceneParams()` and `updateTabUrl()` when the scene needs to update URL state without taking over the active browser location
- Includes tests that assert inactive-tab URL isolation

### `workflowsSceneLogic` and `messageTemplateSceneLogic`

Files:

- `products/workflows/frontend/WorkflowsScene.tsx`
- `products/workflows/frontend/TemplateLibrary/messageTemplateSceneLogic.ts`
- `products/workflows/frontend/TemplateLibrary/MessageTemplate.tsx`

Why they matter:

- `WorkflowsScene` is a clean tab-aware top-level list scene
- `messageTemplateSceneLogic` shows the minimum viable scene root: `tabAwareScene()` plus breadcrumbs
- `MessageTemplate.tsx` shows the `useAttachedLogic` pattern for keeping a child editor logic alive

## Partially tab aware

### `actionLogic`

Files:

- `products/actions/frontend/logics/actionLogic.ts`
- `products/actions/frontend/logics/actionEditLogic.tsx`
- `products/actions/frontend/pages/Action.tsx`

What it already does well:

- Keys logic by `tabId + id`
- Attaches `actionEditLogic` to `actionLogic`
- Preserves form state across tab switches

What it is missing:

- No `tabAwareScene()` scene-root wrapper
- Scene root and resource logic are still the same logic
- URL ownership still lives in nested logic

Migration implication:

- Good candidate to split into a small scene-root logic plus attached resource logic.

### `subscriptionSceneLogic`

Files:

- `frontend/src/scenes/subscriptions/subscriptionSceneLogic.tsx`
- `frontend/src/scenes/subscriptions/subscriptionSceneLogic.test.ts`

What it already does well:

- Keys by `tabId + id`
- Keeps per-tab detail state separate

What it is missing:

- No `tabAwareScene()` guard
- No scene-root router ownership layer

## Not tab aware

### `featureFlagLogic`

Files:

- `frontend/src/scenes/feature-flags/FeatureFlag.tsx`
- `frontend/src/scenes/feature-flags/featureFlagLogic.ts`

Why it is not tab aware:

- Root scene logic keys only by `id`
- Root scene logic owns plain `urlToAction`
- Scene component uses React-local state for scene-level UI state

Likely migration:

- Introduce a dedicated `featureFlagSceneLogic` keyed by `tabId`
- Keep `featureFlagLogic` as an attached child keyed by `tabId + id`
- Move scene-level route state and tab title ownership into the new scene root

### `productTourLogic`

Files:

- `frontend/src/scenes/product-tours/ProductTour.tsx`
- `frontend/src/scenes/product-tours/productTourLogic.ts`

Why it is not tab aware:

- Root scene logic keys only by `id`
- Plain `urlToAction` and `actionToUrl`
- Scene-level edit tab state lives in the resource logic instead of a tab-aware scene root

### `dashboardLogic`

Files:

- `frontend/src/scenes/dashboard/Dashboard.tsx`
- `frontend/src/scenes/dashboard/dashboardLogic.tsx`

Why it is useful as an anti-pattern example:

- Scene export points directly at a resource logic keyed by dashboard id
- Route ownership is in the resource logic
- This shape works for single-page routing but is harder to make truly tab aware than the split-root pattern used by insights and experiments

## Important implementation detail

`sceneLogic` injects `tabId` into:

- scene component props
- scene logic props

That happens in `frontend/src/scenes/sceneLogic.tsx` via:

- `activeSceneComponentParamsWithTabId`
- `activeSceneLogicPropsWithTabId`

This is why a scene-root logic can rely on `tabId` when mounted through `SceneExport.logic`.
