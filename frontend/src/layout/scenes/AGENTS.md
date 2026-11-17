# Scene chrome agent guide (`frontend/src/layout/scenes`)

This directory owns the **scene action surfaces**:

- **`ScenePanel`** (`SceneLayout.tsx`): the per-scene action/info side panel. Scenes fill it with
  `<ScenePanelActionsSection>`, `<ScenePanelInfoSection>`, `<ScenePanelLabel>`, `<ScenePanelDivider>`.
  This is the **legacy** action surface.
- **Scene actions** (`sceneActions/`): a scene declares every action once, as a `SceneAction[]` list, and renders `<SceneActions actions={…} />` above `<SceneTitleSection>`.
  The list feeds every surface that shows actions:
  - With `scene-actions` off, `SceneActionsLegacyMenus` renders it through the menu bar primitives in `components/SceneMenuBar.tsx`: the Mac-style menu bar, or the "More actions" menu under `today-rail-nav`.
  - With `scene-actions` and `today-rail-nav` on, the quill `ActionMenu` renders the "More actions" menu, and the title row shows the actions marked `pinned`, in place of the title's own `actions` prop.
  - The whole surface is still gated by `SCENE_MENU_BAR`: a scene's outer `<Resource>SceneMenuBar` component returns null when it is off.

Scenes never import the menu bar primitives. They are the flag-off renderer, and they go when `scene-actions` ships.

We are mid-migration (`ScenePanel` to scene actions). Until the flag ships everywhere, **both surfaces must stay in sync**.

**`ScenePanel` is deprecated under `today-rail-nav`.** That redesign will remove the side panel's Info tab,
which renders `ScenePanel`, and scene actions take over every action. Keep the dual-write while
the flag-off UI still ships, but build no new surface on `ScenePanel` and treat it as scheduled for removal.

## Rule: every scene action is in the scene's action list

When you add, edit, or remove any action on a scene's `ScenePanel` (a button, toggle, link,
destructive op, metadata input; anything in `<ScenePanelActionsSection>` / `<ScenePanelInfoSection>`),
make the same change in that scene's `SceneAction` list. A feature that only exists on the
`ScenePanel` is invisible to every user with `SCENE_MENU_BAR` on.

This is a dual-write, not a move: keep the `ScenePanel` entry (flag-off path) **and** add the action.

### The title row is derived, never the only home

Every action a user can reach from the `actions` prop of `<SceneTitleSection>` is also in the scene's `SceneAction` list.
Mark the ones the title row shows with `pinned: { order, variant }`: one `primary`, at most two `secondary`, at most two `icon`.
The model drops pins over those caps, and a narrow scene keeps only the last pinned action (the primary, when there is one), since every pinned action is also in the menu.
The `actions` prop stays only as the flag-off title row.
Usage decides which actions are pinned. Promote or demote an action on usage data, not on how important it looks.

### If the scene has no action list yet, create one

Scenes get a co-located `<Resource>SceneMenuBar` component (`CohortSceneMenuBar`, `DashboardSceneMenuBar`, etc).
It returns `null` unless `SCENE_MENU_BAR` is on, builds the list in an inner component, and returns `<SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />`.
Render it immediately **above** `<SceneTitleSection>`, alongside the existing `<ScenePanel>`.

Reference implementations: `products/dashboards/frontend/DashboardSceneMenuBar.tsx` and `products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/ErrorTrackingIssueSceneMenuBar.tsx`.

## Before you write action code, read the skill

The item kinds, groups, sections, destructive rows, panels for rich inputs, pinning, shared action hooks, and optimistic-save patterns live in the **`/scene-menu-bar` skill** (`.agents/skills/scene-menu-bar/SKILL.md`).
Invoke it before adding or moving actions. This guide is the _when/why_; the skill is the _how_.

## Instrumentation is automatic

The menu bar primitives and `sceneActions/SceneActionMenu.tsx` capture `scene menu bar shown` / `menu opened` / `item clicked` (and `searched` in the "More actions" menu) centrally, so you don't wire analytics per scene.
An action's `id` is its `data-attr` and the captured `item`, so keep it stable (`${RESOURCE_TYPE}-menubar-<action>`).
