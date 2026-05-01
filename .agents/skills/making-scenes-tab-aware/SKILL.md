---
name: making-scenes-tab-aware
description: Guides converting PostHog frontend scenes to be tab aware for internal scene tabs. Use when adding or refactoring a `SceneExport` scene, fixing state leaking between internal tabs, preserving scene state across tab switches, or moving scene-level URL state out of child logics. Triggers on files with `SceneExport`, `tabId`, `tabAwareScene`, `urlToAction`, `actionToUrl`, or `useAttachedLogic`.
---

# Making scenes tab aware

PostHog's internal tabs keep scene root logics mounted even when a tab is inactive.
That only works correctly when the scene is designed for it.

A fully tab-aware scene has three properties:

1. The root `SceneExport.logic` is scoped per internal tab.
2. Scene-owned URL sync only reacts for the active tab and updates inactive tabs without hijacking the browser URL.
3. Any child logic that must survive React unmounts is attached to the scene root logic.

`sceneLogic` already injects `tabId` into both the scene component props and the scene logic props.
See `frontend/src/scenes/sceneLogic.tsx`.

## Use this skill when

- Adding a new scene with `SceneExport`
- Refactoring an existing scene that loses filters, edit state, or form state on tab switch
- Fixing state bleed between two internal tabs showing the same scene type
- Replacing plain `urlToAction` / `actionToUrl` in scene root logic
- Splitting a resource logic into a tab-aware scene root plus attached child logic

## Start with an audit

1. Run the audit commands in [references/audit-commands.md](references/audit-commands.md).
2. Compare the current scene against the patterns in [references/repo-patterns.md](references/repo-patterns.md).
3. Work through the migration checklist in [references/migration-checklist.md](references/migration-checklist.md).

## Fast decision guide

### Scene is already fully tab aware

Examples:

- `frontend/src/scenes/insights/insightSceneLogic.tsx`
- `frontend/src/scenes/dashboard/dashboards/dashboardsLogic.ts`
- `products/endpoints/frontend/endpointSceneLogic.tsx`
- `products/workflows/frontend/WorkflowsScene.tsx`

Usually no structural work is needed.
Only follow existing patterns.

### Scene is partially tab aware

Examples:

- `products/actions/frontend/logics/actionLogic.ts`
- `frontend/src/scenes/subscriptions/subscriptionSceneLogic.tsx`

These scenes already isolate instances with `tabId` in their key, but they do not use the scene-level `tabAwareScene()` contract.
Treat them as good raw material for a full migration.

### Scene is not tab aware

Examples:

- `frontend/src/scenes/feature-flags/featureFlagLogic.ts`
- `frontend/src/scenes/product-tours/productTourLogic.ts`
- `frontend/src/scenes/dashboard/dashboardLogic.tsx`

These usually key by resource id, own router bindings directly, or depend on React-local state that disappears on tab switch.
They often need a dedicated scene-root logic added on top of the existing resource logic.

## Core rule

If a logic is the scene root referenced by `SceneExport.logic`, it should normally be keyed by `tabId` and own scene-level router sync.
If a logic is a child resource/editor/detail logic, it can key by `tabId + resource id` and be attached to the scene root with `useAttachedLogic`.

## What to avoid

- Root scene logic keyed only by resource id
- Plain `urlToAction` / `actionToUrl` on the scene root
- URL ownership spread across multiple nested logics
- Important scene state stored in React `useState`
- Child logics mounted only through the view layer when their state must survive tab switches

## Verification

At minimum:

1. Open the same scene type in two internal tabs.
2. Change scene state in one tab.
3. Confirm the other tab keeps its own independent state.
4. Switch away and back.
5. Confirm edit state, filters, and child-logic state are preserved.

Then run the relevant tests plus:

```bash
hogli lint:skills
hogli build:skills
```
