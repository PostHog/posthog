# Audit commands

Use these commands to classify the current scene before refactoring it.

## Find existing fully tab-aware scene roots

```bash
rg -n "tabAwareScene\\(" frontend/src/scenes products -g '!**/generated/**'
```

These are the best local examples to copy.

## Find plain router bindings that may need migration

```bash
rg -n "\\b(urlToAction|actionToUrl)\\(" frontend/src/scenes products -g '!**/generated/**'
```

Interpretation:

- If this is in a scene-root logic, it is usually a migration target.
- If this is in a nested logic, check whether the scene root should own that URL state instead.

## Find attached child logics

```bash
rg -n "useAttachedLogic\\(" frontend/src/scenes products -g '!**/generated/**'
```

These show which scenes already preserve child logic across tab switches.

## Find scene exports

```bash
rg -n "export const scene: SceneExport" frontend/src/scenes products -g '!**/generated/**'
```

For each scene export, inspect:

- `logic`
- `paramsToProps`
- whether the scene component expects `tabId`

## Find logic props that already include `tabId`

```bash
rg -n "tabId[:?]" frontend/src/scenes products -g '!**/generated/**'
```

Interpretation:

- `tabId` present in props/key but no `tabAwareScene()` usually means a partial migration
- no `tabId` at all on a scene-root logic usually means it is not tab aware

## Find scene roots still keyed by resource id

```bash
rg -n "key\\(" frontend/src/scenes products -g '!**/generated/**'
```

Then inspect whether the logic is:

- the `SceneExport.logic` root
- an attached child/resource logic

Root scene keyed by resource id is often a sign you need to split the scene root from the resource logic.
