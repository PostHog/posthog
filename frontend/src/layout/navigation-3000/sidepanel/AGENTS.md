# Side panel agent guide (`frontend/src/layout/navigation-3000/sidepanel`)

The side panel is the right-hand panel with tabs for PostHog AI, Info, Notebooks, Discussion, Activity, Access control and Support.
`sidePanelLogic.tsx` decides which tabs a scene gets.

## Under `today-rail-nav`, several tabs are on their way out

The `today-rail-nav` flag gates a redesign of the whole web app UI.
Under that flag the side panel shrinks, and its tabs move to other surfaces:

- **Info** renders the scene's `ScenePanel`. It is deprecated and will be removed, and the `SceneMenuBar` takes over its actions. See [`layout/scenes/AGENTS.md`](../../scenes/AGENTS.md) when you change a scene's actions.
- **Support** opens from the menu bar's Help menu instead of a tab bar button.
- **Notebooks** and **Discussion** are hidden from the tab bar (`visibleTabs`). Their panels still open from their existing entry points, such as a comment button or "Add to notebook". They will be removed from the side panel or moved; the new home is not decided yet.

Do not build new features on the Info, Notebooks or Discussion tabs.
A change to them must keep working with the flag off, because the current UI still ships them.
