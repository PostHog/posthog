# Today shell agent guide (`frontend/src/layout/today`)

## Products pane

- **The Products pane lists every product the current navigation lists, except Home.** People go there to find everything. Home is the rail's Home item, so it is the only page left out. Never filter any other product out of `todayProductsLogic`'s `products`, even when another rail pane (People, Analytics) also links to it. Opening such a product from the Products pane keeps that pane open (`paneAfterNavigation` in `todayShellLogic.ts`). `todayProductsLogic.test.ts` fails if the list drifts from `getNavProductItems` less Home.

## Hover cards

These rules apply to every sidebar list the rail opens, for example Products, Spaces, People and Analytics.

- **A row shows its hover card only through `TodayPreviewTrigger`, under a `TodayPreviewCardProvider`.** Do not give a row a second hover card of its own. A tooltip on a control inside the row, such as the star button, is fine. The trigger carries the shared behavior below, and a row that skips it loses that behavior.
- **A click on a row closes its hover card, and the card stays shut for that row until the pointer comes back to it or focus leaves it.** A card left open after a click covers the page the click opened. `TodayPreviewTrigger` does this with `dismissFor` and `rearm` on the card context. Do not remove it, and do not stop a click on a row from reaching the trigger's capture handler.
- **An open row menu keeps the card shut.** Report the menu with `useTodayPreviewMenuReport` from its `onOpenChange`.

## Recents sections

These rules apply to every sidebar section that lists items a person recently opened, for example Recents in the People and Analytics panes.

- **A click on a row must not move the row.** A row that moves when it is clicked leaves the pointer over a different row.
- **The section shows the newest items, sorted by name.** Use `newestByName` from `todayNewestByName.ts`. Do not sort by recency, and do not write a second sort. The list changes only when a person opens an item that is not in the list.
- **The stored list stays newest first.** Sort in a selector or where the section's list is built. The limit needs the recency order to choose which items to keep, so do not write the sorted order over a recency order you still need.
- **A scene reports its own record.** A section reads the open record from the scene logic, for example the `TODAY_PEOPLE_RECENT_KEY` selector in `todayPeople.ts`, which is null until the record loads. Do not read a recent from breadcrumbs or the URL: they show placeholder names and the previous page while a page loads, and rows sort by name.
