# Scene chrome agent guide (`frontend/src/layout/scenes`)

This directory owns the **scene action surfaces**:

- **`ScenePanel`** (`SceneLayout.tsx`): the per-scene action/info side panel. Scenes fill it with
  `<ScenePanelActionsSection>`, `<ScenePanelInfoSection>`, `<ScenePanelLabel>`, `<ScenePanelDivider>`.
  This is the **legacy** action surface.
- **`SceneMenuBar`** (`components/SceneMenuBar.tsx`): the Mac-style menu bar above `<SceneTitleSection>`
  that consolidates those actions into File / Edit / View / Metadata / Staff only menus. This is the
  **new** action surface, gated behind the `SCENE_MENU_BAR` feature flag.

We are mid-migration (`ScenePanel` to `SceneMenuBar`). Until the flag ships everywhere, **both surfaces
must stay in sync**.

## Rule: every scene action goes in the SceneMenuBar

When you add, edit, or remove any action/feature on a scene's `ScenePanel` (a button, toggle, link,
destructive op, metadata input; anything in `<ScenePanelActionsSection>` / `<ScenePanelInfoSection>`),
you **must** make the same change in that scene's `SceneMenuBar`. A feature that only exists on the
`ScenePanel` is invisible to every user with `SCENE_MENU_BAR` on.

This is a dual-write, not a move: keep the `ScenePanel` entry (flag-off path) **and** add the menu bar
entry (flag-on path). Don't delete `ScenePanel` actions while the flag is still rolling out.

### If the scene has no SceneMenuBar yet, create one

Scenes get a co-located `<Resource>SceneMenuBar` component (`CohortSceneMenuBar`, `DashboardSceneMenuBar`,
`NotebookSceneMenuBar`, etc). If the scene you're touching doesn't have one, add it:

1. Create `<Resource>SceneMenuBar.tsx` next to the scene. It returns `null` unless the flag is on:

   ```tsx
   export function CohortSceneMenuBar({ id }: { id?: CohortType['id'] }): JSX.Element | null {
     const { featureFlags } = useValues(featureFlagLogic)
     if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
       return null
     }
     return <CohortSceneMenuBarInner id={id} />
   }
   ```

2. Build the menus with the primitives from `~/layout/scenes/components/SceneMenuBar`, mirroring the
   actions already on the scene's `ScenePanel` into the canonical menu set (File / Edit / View /
   Metadata / Staff only).

3. Render it in the scene immediately **above** `<SceneTitleSection>`, alongside the existing
   `<ScenePanel>`:

   ```tsx
   <CohortSceneMenuBar id={id} />
   <ScenePanel>…</ScenePanel>
   <SceneTitleSection … />
   ```

Reference implementations: `scenes/cohorts/CohortSceneMenuBar.tsx`,
`scenes/dashboard/DashboardSceneMenuBar.tsx`, `scenes/notebooks/NotebookSceneMenuBar.tsx`.

## Before you write menu code, read the skill

The component taxonomy, canonical menu order, destructive-action styling, `opensFloatingUi`, rich-input
(`SceneMenuBarPopover` + `TagsCombobox`) wiring, empty-menu handling, and optimistic-save patterns all
live in the **`/scene-menu-bar` skill** (`.agents/skills/scene-menu-bar/SKILL.md`). Invoke it before
adding or moving menu items. This guide is the _when/why_; the skill is the _how_.

## Instrumentation is automatic

`SceneMenuBar.tsx` captures `scene menu bar shown` / `menu opened` / `item clicked` centrally, so you
don't wire analytics per scene. Just give items a stable `data-attr` (`${RESOURCE_TYPE}-menubar-<action>`)
so the captured `item` is meaningful.

## Alpha/beta status tags are automatic

`SceneTitleSection` renders the same `ALPHA` / `BETA` tag next to the title that the product/tool shows
in the navbar. The source of truth is the product manifest — a `tags: ['beta']` (or `['alpha']`) entry in
`treeItemsProducts`, keyed to the scene via `sceneKey` / `sceneKeys` (see `sceneStatusTags.ts`). Don't
hand-add a status tag via `nameSuffix`; tag the product in its manifest instead, so the navbar and the
title stay in sync and graduating out of beta is a one-line change. (Special navbar entries not in the
product tree, like Inbox, are listed explicitly in `sceneStatusTags.ts`.)
