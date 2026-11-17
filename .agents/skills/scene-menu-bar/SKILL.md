---
name: scene-menu-bar
description: Conventions for a scene's actions, declared once as a SceneAction list that feeds the menu bar, the "More actions" menu and the title row buttons. Use when adding or moving a scene action, pinning an action to the title row, building a new scene's action list, gating actions behind feature flags, or wiring rich inputs (tags, comboboxes) into a scene's menu.
---

# Scene action conventions

A scene declares its actions once, as a `SceneAction[]` list, and renders `<SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />` above `<SceneTitleSection>`.
The list renders as the Mac-style menu bar, as the "More actions" menu after the scene name under `today-rail-nav`, and, under `scene-actions`, as the title row buttons too.
`frontend/src/layout/scenes/AGENTS.md` says which flag draws which surface.

| File                                                         | Holds                                                              |
| ------------------------------------------------------------ | ------------------------------------------------------------------ |
| `layout/scenes/sceneActions/sceneActionModel.ts`             | `SceneAction`, groups, pinning caps, and the tree the menu renders |
| `packages/quill/packages/components/src/action-menu-tree.ts` | The item kinds a `SceneAction` extends, and the search             |
| `layout/scenes/sceneActions/SceneActions.tsx`                | The component a scene renders                                      |
| `layout/scenes/sceneActions/SceneActions.stories.tsx`        | Every item kind in one list, rendered under both flags             |

Reference scenes: `products/dashboards/frontend/DashboardSceneMenuBar.tsx` (large File menu, submenus, toggles, conditional pins) and `products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/ErrorTrackingIssueSceneMenuBar.tsx` (radios, panels, pins with a custom title control).

## An action

```tsx
const actions: SceneAction[] = [
    {
        group: 'file',
        section: 'share',
        id: `${RESOURCE_TYPE}-menubar-subscribe`, // also the data-attr and the captured analytics item
        label: 'Subscribe',
        icon: <IconBell />,
        onSelect: subscribe,
        pinned: { order: 2, variant: 'secondary' },
    },
    ...(canDelete
        ? ([
              {
                  group: 'file',
                  section: 'delete',
                  id: `${RESOURCE_TYPE}-menubar-delete`,
                  label: 'Delete dashboard',
                  icon: <IconTrash />,
                  destructive: true,
                  disabledReason: getAccessControlDisabledReason(…) ?? undefined,
                  onSelect: remove,
              },
          ] satisfies SceneAction[])
        : []),
]
```

| `type`             | Use for                                                                  | Fields                                                             |
| ------------------ | ------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `action` (default) | A command or a navigation                                                | `onSelect`, `destructive`, `opensFloatingUi`, `shortcut`           |
| `checkbox`         | A toggle. Use a stable label (`Pinned`, not `Pin/Unpin`)                 | `checked`, `onCheckedChange`                                       |
| `radio`            | One of several. `label` names the choice ("Tile density")                | `value`, `options`, `onValueChange`                                |
| `submenu`          | Create, Export, Add to notebook                                          | `items`, `display: 'submenu'`, `searchable: false`, `onOpenChange` |
| `panel`            | Rich inputs: tags, comboboxes, forms. Opens a popover; inputs work there | `render`, `panelClassName`                                         |

Every kind takes `disabledReason`, `tooltip`, `section` and `keywords` (extra search words).
`id` is a wire string: keep it when you move or relabel an action.

## Groups and order

`group` picks the menu. Known groups render in this order with these labels; any other string becomes a menu with that label, after View.

| Group                 | Holds                                                                                                                                                                           |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `file`                | A `Create` submenu first (section `create`), then project tree items, copy to project, Terraform, scene file ops, an `Export` submenu, then destructive rows (section `delete`) |
| `edit`                | Duplicate, rename, scene edits, state changes (Pause/Resume, Activate/Deactivate, status), then toggles (section `toggles`)                                                     |
| `view` (when needed)  | Navigation to see something related: recordings, metalytics, related insights                                                                                                   |
| `metadata`            | `panel` actions. They sit on the top level of the menu, not in a submenu: "Metadata…" for tags, activity, references, comments                                                  |
| `staff` (when needed) | Debug panels and internal toggles. Add only for staff, impersonated or self-hosted users                                                                                        |

State lives in Edit: no separate State menu.
Help (Settings, Docs, Support) is added to every scene. Never declare a `help` action.

## Rules

- **Sections, not separators.** Rows next to each other with different `section` values get a separator. A labeled group or radio starts its own section.
- **Destructive rows** (Delete, Archive, Restore) set `destructive: true`, sit last in File, and carry their access control as `disabledReason`. The "More actions" menu moves them to the end of its top level.
- **`opensFloatingUi`** appends "…" to rows that open a modal, popover, dialog or side panel. Skip it for navigations, direct actions, toggles and destructive rows.
- **Empty menus need no handling.** A menu or submenu with no rows is left out.
- **Submenus nest one level.** Inside a menu, a submenu is a labeled group of rows. `display: 'submenu'` keeps a real submenu, for a long toggle list (Web analytics' visible tiles) or one that holds another choice (Dashboard's Customize).
- **`searchable: false`** keeps a long data list, such as notebooks, out of the search. Load such a list in `onOpenChange`, never on mount.
- **Conditional actions** spread an empty array; never put `false` or `null` in the list.
- **Hooks before returns.** Shared action hooks are hooks: call them before any early return.

## Pinning to the title row

`pinned: { order, variant }` shows an action in the title row as well as in the menu.
One `primary`, at most two `secondary`, at most two `icon`; the model drops the rest, so the menu stays the only home of everything else.
A narrow scene keeps only the last pinned action: the primary, when there is one.
Pick pins on usage data, not on how important an action looks.

The default title control follows the kind: a button for an action, a toggle for a checkbox, a dropdown for a radio or submenu, a popover for a panel.
`pinned.render` replaces it for a control the default cannot draw, such as a select with custom visuals.
A pin can be conditional: `pinned: canUndo ? { order: 0, variant: 'icon' } : undefined`.

The scene keeps its `actions` prop on `<SceneTitleSection>` for the flag-off title row. Every action in it must also be in the list.

## Shared action hooks

| Hook                                                            | Returns                                                      |
| --------------------------------------------------------------- | ------------------------------------------------------------ |
| `useSceneFileActions(key, { group, section })`                  | Open in project tree, Move, Star. Empty without a tree entry |
| `useScenePinAction(key, { group, section })`                    | Pin to sidebar, under `today-rail-nav`                       |
| `useAddToNotebookAction(key, { notebookSelectButtonProps, … })` | The "Add to notebook" submenu                                |
| `useAnalyticsCollectionActions(target, key, { … })`             | Add to, move between, or remove from a collection            |

The first three live in `lib/components/Scenes/`, the last in `scenes/analytics/`.

## Rich inputs and optimistic saves

Put text inputs, comboboxes and tag pickers in a `panel`, never in a row: menu rows intercept keystrokes.
Use `<SceneTagsCombobox>` (`lib/components/Scenes/SceneTagsCombobox.tsx`) for tags.

Autosave from a panel with a kea listener that:

1. Updates optimistically before the API call.
2. Debounces with `await breakpoint(250)`.
3. Calls `breakpoint()` after the response, to bail when a newer call superseded this one.
4. Compares as sets before reconciling, so a reordered server response does not reorder the chips.
5. Re-throws `error.isBreakpoint`.

`saveTagsInline` in `frontend/src/scenes/feature-flags/featureFlagLogic.ts` is the reference.

## Auditing a scene

Map every `ScenePanel` item and every title action to: its group, whether it is destructive, whether it opens floating UI, whether it is a toggle or a choice, its gates (saved state, flags, access control, multi-project), and whether the title row pins it.
