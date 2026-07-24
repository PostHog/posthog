---
name: scene-menu-bar
description: Conventions for adding or editing the SceneMenuBar above a scene's <SceneTitleSection>. Use when adding new menu items, moving items between menus, gating behind feature flags, building a new scene's menubar, or wiring rich inputs (tags, combobox) into the bar.
---

# SceneMenuBar conventions

PostHog scenes render a Mac-style menu bar above `<SceneTitleSection>` that consolidates
ScenePanel actions into a discoverable, keyboard-navigable surface. This skill documents
the taxonomy, the available primitives, and the wiring rules.

The whole bar is gated by the `SCENE_MENU_BAR` feature flag (see `lib/constants.tsx`).

## Components

All primitives live in `frontend/src/layout/scenes/components/SceneMenuBar.tsx`.

| Component                                              | Use for                                                                                                                                                                                                                                                  |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<SceneMenuBar>`                                       | Top-level wrapper; renders above `<SceneTitleSection>`. Includes the universal right cluster (PostHog AI / Docs / Support).                                                                                                                              |
| `<SceneMenuBarMenu label>`                             | Top-level menu (File / Edit / View / Metadata / Staff only).                                                                                                                                                                                             |
| `<SceneMenuBarSubMenu label>`                          | Nested sub-menu inside a `SceneMenuBarMenu` (e.g. `Create`, `Export`, `Add to notebook`). Auto-prepends a blank icon slot to the trigger so the label aligns with icon-bearing siblings — pass `withIconBlank={false}` to opt out.                       |
| `<SceneMenuBarItem>`                                   | Standard menu item (action / navigation).                                                                                                                                                                                                                |
| `<SceneMenuBarCheckboxItem>`                           | Toggle item — reflects boolean state via checkmark.                                                                                                                                                                                                      |
| `<SceneMenuBarRadioGroup>` + `<SceneMenuBarRadioItem>` | One-of-many mutually-exclusive options.                                                                                                                                                                                                                  |
| `<SceneMenuBarSeparator>`                              | Horizontal divider between groups.                                                                                                                                                                                                                       |
| `<SceneMenuBarShortcut>`                               | Right-aligned keyboard shortcut hint.                                                                                                                                                                                                                    |
| `<SceneMenuBarPopover label>`                          | Drop-in alternative to `SceneMenuBarMenu` when content needs rich form controls (text inputs, comboboxes). Uses Popover under the hood — Menu.Popup intercepts keystrokes and blocks inputs. Trigger does NOT participate in CompositeRoot keyboard nav. |

## Canonical menu set (in order)

| Menu                                       | Items                                                                                                                                                                                                                                  |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **File**                                   | `+ Create` sub-menu (top), ── , project tree items (Open / Move / Star), Copy to another project, Manage with Terraform, scene-specific file ops, Export sub-menu, ──, **Delete / Archive / Restore** (destructive at the very bottom) |
| **Edit**                                   | Duplicate, Rename, Edit in SQL editor, scene-specific edits, state mutations (Pause/Resume, Activate/Deactivate), ──, toggle group (checkbox/radio items, separated by `<SceneMenuBarSeparator>` from regular items)                   |
| **View** _(conditional)_                   | Cross-resource viewing — View recordings, View metalytics, View related insights, etc. Anything that navigates to _see_ something tangentially related to the current resource. Skip when empty.                                       |
| **Metadata** _(use `SceneMenuBarPopover`)_ | Tags, Evaluation contexts, Stage, Activity indicator, External references, Comments, etc.                                                                                                                                              |
| **Staff only** _(conditional)_             | Debug panels, staff-only toggles. Only render for staff / superpowers / impersonated / non-cloud users.                                                                                                                                |

> **State lives in Edit.** Pause/Resume, Activate/Deactivate, Favorite/Pin toggles and similar
> state mutations all live inside the Edit menu — usually at the bottom, after a
> `<SceneMenuBarSeparator>` if there's a toggle group. Don't create a separate `State` menu.

Right cluster is fixed and universal: **PostHog AI · Docs · Support**. Do not add to it.

## Rules

### Destructive actions (Delete / Archive / Restore)

- Live at the **bottom of File**, separated from the file ops above by a `<SceneMenuBarSeparator>`.
- Pass `variant="destructive"` for visual treatment (red text + icon).
- Do **not** add `opensFloatingUi` to destructive items even when they open a confirmation dialog — the destructive variant + clear label are signal enough.
- Wrap with `<AccessControlAction>` where the resource has access control levels.

### Toggle groups

- Group all `<SceneMenuBarCheckboxItem>` and `<SceneMenuBarRadioGroup>` items together.
- Separate them from regular action items with `<SceneMenuBarSeparator>` above and (if more items follow) below.
- Use stable labels — the checkmark conveys state: `Pinned` not `Pin/Unpin`, `Show debug panel` not `Show/Hide debug panel`.
- Radios for mutually-exclusive choices (`<SceneMenuBarRadioGroup value onValueChange>`).

### `opensFloatingUi` prop

Append `…` to the item label as a Mac-style affordance for items that open additional floating UI:

- ✅ **Use** for: modal, popover, dialog, side panel openers
- ❌ **Skip** for: same-page navigations, direct actions, destructive items (the destructive style already signals consequence), toggle items

### `+ Create` cross-sells

- Nest inside a `<SceneMenuBarSubMenu label="Create">` at the **top of File**.
- Place a `<SceneMenuBarSeparator>` between Create and the rest of File.
- Cross-sells: Cohort, Survey, Dashboard, Notebook, Endpoint, Subscription, Alert, Share or embed.

### Empty menus

`SceneMenuBarMenu` auto-disables its trigger when its children render nothing at compile
time — e.g. `{false && <Item/>}`, `{null}`, or an empty fragment. The trigger stays
visible (greyed out, `cursor-not-allowed`) so the menu set still communicates the bar's
capabilities to the user.

For menus whose children may render null at runtime (the most common case is
`<SceneMenuBarFileItems>`, which returns null when no project-tree entry is registered),
the parent **cannot detect** that the popup will be empty. You must either:

1. **Pass `disabled` explicitly** based on the same value the children depend on, e.g.:

   ```tsx
   const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
   const hasFileItems = !!projectTreeRefEntry
   <SceneMenuBarMenu label="File" disabled={!hasFileItems}>
       {hasFileItems && <SceneMenuBarFileItems dataAttrKey="…" />}
   </SceneMenuBarMenu>
   ```

2. **Gate the whole menu** at the parent if it can't render anything useful:

   ```tsx
   {
     hasAnyEditItem && <SceneMenuBarMenu label="Edit">…</SceneMenuBarMenu>
   }
   ```

Prefer (1) when the menu's presence is part of the scene's identity (File should always
be visible even if disabled), and (2) when the menu is genuinely optional (View, Staff
only).

### Tags / Evaluation contexts / other rich inputs

- Must live inside a `<SceneMenuBarPopover>`, not a `<SceneMenuBarMenu>`. Menu popups
  intercept keystrokes (typeahead, arrow nav) and prevent text inputs from receiving
  input.
- Use `<TagsCombobox>` (`lib/components/Scenes/TagsCombobox.tsx`) for multi-select chip
  inputs — selection-only by default; pass `allowCustomValues` to surface a
  "Create new {noun} '...'" item at the bottom.
- Use `<SceneTagsCombobox>` (`lib/components/Scenes/SceneTagsCombobox.tsx`) as the
  ready-made wrapper that swaps in for `<SceneTags>` under `SCENE_MENU_BAR`.

### Optimistic saves with debounce

When autosaving from menubar inputs (tags, toggles), use a kea listener with:

1. **Optimistic update** (`setX` + `updateX`) immediately, before the API call.
2. **`await breakpoint(250)`** to debounce rapid changes.
3. **`breakpoint()` after the API response** to bail if a newer call has superseded this one.
4. **Set-equality check** before reconciling with server response to avoid re-ordering
   when the server returns differently-ordered values.
5. Re-throw `error.isBreakpoint` so kea swallows it silently.

See `saveTagsInline` in `frontend/src/scenes/feature-flags/featureFlagLogic.ts`.

### File menu — project tree items

Use `<SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />` at the bottom of File
(before the destructive separator) to render Open in project tree, Move to folder,
Add/Remove starred. It auto-hides when no project-tree entry is registered.

### Right cluster

Lives outside the `<Menubar>` wrapper to keep CompositeRoot keyboard nav working for
the actual menus. Do not add items here without UX review.

### Layout-aware bleed

`<SceneMenuBar>` reads `sceneLayoutLogic.sceneLayoutConfig.layout` and bleeds past the
scene container's padding (`-mx-4 -mt-4`) **only** when the layout is padded:
`app`, `app-container`, or `app-full-scene-height`. For unpadded layouts (`app-raw`,
`app-raw-no-header`, `plain`) the negatives would overshoot and visually break the
header, so they're skipped. You don't need to do anything in your scene — just register
the right `SceneConfig.layout` and the bar adapts. Sentinel: a `data-scene-layout`
attribute is set on the wrapper for debugging.

## Scenes already migrated

- Feature Flag — `frontend/src/scenes/feature-flags/FeatureFlag.tsx`
- Insight — `frontend/src/scenes/insights/SidePanel/InsightSceneMenuBar.tsx`
- Dashboard — `frontend/src/scenes/dashboard/DashboardSceneMenuBar.tsx`

When migrating a new scene, follow the `<Scene>SceneMenuBar.tsx` pattern (component
that reads `featureFlagLogic`, early-returns null if the flag is off, otherwise renders
the bar). Mount it directly above `<SceneTitleSection>`.

## Auditing a scene

When migrating a scene, take its existing ScenePanel and map every item to:

1. Which menu it belongs to (File / Edit / View / Metadata / Staff only).
2. Whether it needs `variant="destructive"` (delete/archive/remove).
3. Whether it needs `opensFloatingUi` (opens modal/popover/dialog/side panel).
4. Whether it's a toggle (use `SceneMenuBarCheckboxItem`).
5. What gates apply (saved state, FF, AccessControl, multi-project).

See `/Users/adamleithp/Desktop/scene-menu-bar-grouping.md` for the running inventory of
all ScenePanel items across PostHog and their proposed menu placement.
