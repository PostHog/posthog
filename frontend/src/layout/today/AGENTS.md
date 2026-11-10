# Today shell agent guide (`frontend/src/layout/today`)

## Products pane

- **The Products pane lists every product the current navigation lists, except Home.** People go there to find everything. Home is the rail's Home item, so it is the only page left out. Never filter any other product out of `todayProductsLogic`'s `products`, even when another rail pane (People, Analytics) also links to it. Opening such a product from the Products pane keeps that pane open (`paneAfterNavigation` in `todayShellLogic.ts`). `todayProductsLogic.test.ts` fails if the list drifts from `getNavProductItems` less Home.

## Recents sections

These rules apply to every sidebar section that lists items a person recently opened, for example Recents in the People and Analytics panes.

- **A click on a row must not move the row.** A row that moves when it is clicked leaves the pointer over a different row.
- **The section shows the newest items, sorted by name.** Use `newestByName` from `todayNewestByName.ts`. Do not sort by recency, and do not write a second sort. The list changes only when a person opens an item that is not in the list.
- **The stored list stays newest first.** Sort in a selector or where the section's list is built. The limit needs the recency order to choose which items to keep, so do not write the sorted order over a recency order you still need.
- **A scene reports its own record.** A section reads the open record from the scene logic, for example the `TODAY_PEOPLE_RECENT_KEY` selector in `todayPeople.ts`, which is null until the record loads. Do not read a recent from breadcrumbs or the URL: they show placeholder names and the previous page while a page loads, and rows sort by name.
