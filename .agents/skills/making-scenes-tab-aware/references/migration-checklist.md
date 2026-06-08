# Migration checklist

Use this checklist when converting a scene.

## 1. Confirm the scene boundary

- Find the `SceneExport` object.
- Identify the intended scene-root logic.
- Check whether the current scene export points directly at a resource/detail logic keyed by id.

If the scene export points straight at a resource logic like `featureFlagLogic({ id })`, that is usually the first thing to change.

## 2. Decide whether you need a new scene-root logic

You usually need a dedicated scene-root logic when any of these are true:

- The current root logic keys by resource id instead of `tabId`
- The current root logic owns route params, search params, or edit-mode state directly
- The scene has child editor/detail logic that should survive tab switches
- The scene uses React local state for state that should persist per tab

Good split pattern:

```text
SceneExport.logic -> featureFlagSceneLogic({ tabId, id })
                      └── useAttachedLogic(featureFlagLogic({ tabId, id }), featureFlagSceneLogic({ tabId, id }))
```

The scene root owns tab-scoped routing and breadcrumbs.
The child logic owns the resource/editor state.

## 3. Make the scene root tab aware

On the root scene logic:

- Add `tabId?: string` to props if not already present
- Add `tabAwareScene()`
- Do not key the root scene by resource id only
- Add a `breadcrumbs` selector

Important:

- `tabAwareScene()` is best for scene-root logics
- child logics can still key by `tabId + resource id`

## 4. Move scene-owned URL state into the root scene logic

At the scene root:

- Replace `urlToAction` with `tabAwareUrlToAction`
- Replace `actionToUrl` with `tabAwareActionToUrl`
- Parse route params, search params, and hash params into scene-root reducers/actions

Prefer this ownership model:

```text
URL <-> scene-root logic reducers/selectors
scene-root logic -> child logic props/actions
```

Avoid:

```text
URL <-> nested editor logic
URL <-> table logic
URL <-> modal logic
```

If a nested logic must read or update the inactive tab's URL state, use:

- `getTabSceneParams(tabId)`
- `updateTabUrl(tabId, pathname, searchParams, hashParams)`

Prefer using those from the scene root, not deep child logics.

## 5. Preserve child logic lifetime across tab switches

Remember:

- inactive scene roots stay mounted
- React-mounted child logics unmount when their component disappears

If a child logic must survive tab switches:

- mount it under the scene root with `useAttachedLogic`

Example:

```tsx
const sceneLogic = messageTemplateSceneLogic(props)
const logic = messageTemplateLogic(props)

useAttachedLogic(logic, sceneLogic)
```

Use this for:

- editors
- forms
- heavy data logics
- nested resource logic

## 6. Review React local state

Any state that should survive tab switches should not live in `useState`.

Move it into Kea when it represents:

- selected scene tab
- edit/view mode
- filters
- URL-backed state
- current sub-resource selection
- in-progress form/edit state

React local state is fine for truly disposable UI-only state.

## 7. Make keys intentional

Typical patterns:

- Scene root: `tabAwareScene()` only
- Attached child resource logic: `key(({ id, tabId }) => \`${tabId ?? ''}-${id}\`)`
- Draft/editor child logic: `key(({ tabId, id }) => \`${id}-${tabId}\`)`

Use resource-id-only keys only when the logic is intentionally global and not tab scoped.

## 8. Keep tab titles and back buttons correct

The scene root should expose `breadcrumbs`.

Remember:

- last breadcrumb controls tab title and icon
- previous breadcrumb controls the back button
- additional breadcrumbs are ignored by the tab chrome

## 9. Add or update tests

Recommended coverage:

- logic can mount with `tabId`
- two tab ids produce isolated state
- inactive-tab URL updates do not mutate the active browser URL
- switching away and back keeps attached child logic state

Useful references:

- `frontend/src/scenes/dashboard/dashboards/dashboardsLogic.test.ts`
- `products/endpoints/frontend/endpointSceneLogic.test.ts`
- `frontend/src/scenes/subscriptions/subscriptionSceneLogic.test.ts`

## 10. Manual verification

Test this flow in the app:

1. Open scene A in tab 1.
2. Open the same scene type in tab 2.
3. Change filters/edit mode/sub-tab in tab 1.
4. Confirm tab 2 is unchanged.
5. Switch away from tab 1 and back.
6. Confirm scene state is restored.
7. If the inactive tab updates its own URL-backed state, confirm the browser URL does not jump while another tab is active.
