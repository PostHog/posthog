# Taxonomic filter search loading

The legacy picker and the rebuilt menu hold aggregated search results until the contributing categories settle. This prevents late category results from moving a choice under the pointer. Only categories offered by the picker contribute to that wait; a category-specific list waits for its own results. Recent and Pinned scopes use pre-resolved entries and never enter this search loading barrier.

A category shows results for the current query only. It clears its earlier rows when the current query cannot fetch, such as a query below the category minimum length or a request that failed.

Scoped property searches return properties associated with the selected events. A separate unscoped request counts matches across the project so the picker can offer an expansion to other properties.

The expansion count must not delay the scoped results or keep the aggregate reveal barrier closed. It can add an expansion option below the results after they appear. A failed count leaves the scoped results usable, and a count from an earlier search must not affect the current search. Expanding explicitly starts a full-results request and uses the normal list loading state.

The legacy implementation separates these requests in `infiniteListLogic.ts`; the rebuilt implementation uses independent resources in `hooks/useGroupList.ts`. Keep this behavior consistent across both implementations.

## Remote search cadence, paging and capped counts

Both implementations wait 500 ms after the last keystroke before they send a remote search, and treat that wait as loading, so the list is held the same way as for a request in flight. Local-only categories, and the client-filtered first page of a category, filter on every keystroke.

Remote categories load 100 rows per page. The legacy list loads the next page as the user scrolls. The rebuilt menu offers a "Show more" row until the loaded rows reach the reported count or a page comes back short.

The definition endpoints stop counting at 10,000 rows for large projects, so a count of 10,000 means "10,000 or more". Category badges, expansion labels and the data management tables render such a count as `10,000+`. `frontend/src/lib/utils/definitionCount.ts` mirrors the backend cap.

## Event list pagination

The event definitions API counts matching rows separately and applies `LIMIT` and `OFFSET` in PostgreSQL. The count describes all matches, including matches outside the requested page. Explicit ordering uses the project-unique event name as a final tie-breaker so equal timestamps do not cause skipped or repeated results between pages.

Tag-filtered requests retain ORM pagination after resolving matching event IDs. Both paths preserve the same response fields and project scope, including legacy definitions whose `project_id` is null.
