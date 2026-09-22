# Taxonomic filter search loading

The classic picker and the rebuilt menu hold aggregated search results until the contributing categories settle. This prevents late category results from moving a choice under the pointer. Only categories offered by the picker contribute to that wait; a category-specific list waits for its own results. Recent and Pinned scopes use pre-resolved entries and never enter this search loading barrier.

The classic picker shows its active category in the search input. A person can dock the category rail from that menu. This preference persists for that person and project. A narrow picker hides the rail and shows the category control in the search input.

The rail starts undocked. `taxonomic filter category rail toggled` records whether it is docked. `taxonomic filter closed` records the final `categoryRailDocked` state so reports can show which people keep the rail docked.

A category shows results for the current query only. It clears its earlier rows when the current query cannot fetch, such as a query below the category minimum length or a request that failed.

Scoped property searches return properties associated with the selected events. A separate unscoped request counts matches across the project so the picker can offer an expansion to other properties.

The expansion count must not delay the scoped results or keep the aggregate reveal barrier closed. It can add an expansion option below the results after they appear. A failed count leaves the scoped results usable, and a count from an earlier search must not affect the current search. Expanding explicitly starts a full-results request and uses the normal list loading state.

The legacy implementation separates these requests in `infiniteListLogic.ts`; the rebuilt implementation uses independent resources in `hooks/useGroupList.ts`. Keep this behavior consistent across both implementations.

## Action definitions

Event-only insight editors and closed breakdown pickers do not load the action list.
Action series load their definitions to resolve names and event-scoped properties.
Opening an event picker that offers Actions loads the list; later opens reuse the shared cache.
The classic popover unmounts after its close transition and starts with a fresh search when reopened.

## Typing and rendering

The legacy picker debounces API searches for 500 ms after the last keystroke, including while the initial response is loading.
The initial empty-query load bypasses this wait.
Local filtering and rendering still update on each keystroke.

## Event list pagination

The event definitions API counts matching rows separately and applies `LIMIT` and `OFFSET` in PostgreSQL. The count describes all matches, including matches outside the requested page. Explicit ordering uses the project-unique event name as a final tie-breaker so equal timestamps do not cause skipped or repeated results between pages.

Tag-filtered requests retain ORM pagination after resolving matching event IDs. Both paths preserve the same response fields and project scope, including legacy definitions whose `project_id` is null.

## Cohort names on individual insights

Individual insight pages load cohort names by ID from the query's cohort property filters and cohort breakdowns.
This includes edit, subscriptions, alerts, and sharing routes with optional item IDs; the separate `quick-start` scene keeps the full list load.
These requests use the parent project ID, which can differ from the current environment ID.
They reuse the shared cohort cache when the query changes, and resolve nested cohort references for definition popovers.
The shared model queues cohort detail requests with at most 10 in flight across overlapping loads and nested references.
This limits concurrent requests, not the total number of references an insight can resolve.
An insight without cohort references does not load the cohort list.
The insight breadcrumb subscribes to the resolved insight name so generated titles update when cohort names arrive.
The cohort picker continues to load its options independently.
Opening an AI visualization's definition resolves its cohort references even when the chart is collapsed.
Navigating from a dashboard reuses the cohorts already in the shared cache and fetches only missing references.

Other pages retain the shared model's full-list loading behavior.
The model stays mounted across navigation, so leaving an individual insight must trigger the list load if it has not already run.
Keep both `cohortsById` and `allCohorts.results` populated: insight titles and filter chips use the former, while charts, legends, tooltips, and color settings use the latter.
