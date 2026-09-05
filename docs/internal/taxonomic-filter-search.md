# Taxonomic filter search loading

The legacy picker and the rebuilt menu hold aggregated search results until the contributing categories settle. This prevents late category results from moving a choice under the pointer. Only categories offered by the picker contribute to that wait; a category-specific list waits for its own results. Recent and Pinned scopes use pre-resolved entries and never enter this search loading barrier.

A category shows results for the current query only. It clears its earlier rows when the current query cannot fetch, such as a query below the category minimum length or a request that failed.

Scoped property searches return properties associated with the selected events. A separate unscoped request counts matches across the project so the picker can offer an expansion to other properties.

The expansion count must not delay the scoped results or keep the aggregate reveal barrier closed. It can add an expansion option below the results after they appear. A failed count leaves the scoped results usable, and a count from an earlier search must not affect the current search. Expanding explicitly starts a full-results request and uses the normal list loading state.

The legacy implementation separates these requests in `infiniteListLogic.ts`; the rebuilt implementation uses independent resources in `hooks/useGroupList.ts`. Keep this behavior consistent across both implementations.

## Event list pagination

The event definitions API counts matching rows separately and applies `LIMIT` and `OFFSET` in PostgreSQL. The count describes all matches, including matches outside the requested page. Explicit ordering uses the project-unique event name as a final tie-breaker so equal timestamps do not cause skipped or repeated results between pages.

Tag-filtered requests retain ORM pagination after resolving matching event IDs. Both paths preserve the same response fields and project scope, including legacy definitions whose `project_id` is null.

## Project-first event search trial

The `event-definition-project-first-search` flag selects a project-first SQL plan for nonempty event searches. Its distinct ID is the project ID as a string. Evaluation is local and sends no flag events; an unavailable or disabled flag keeps the default plan. Empty searches retain the default plan without evaluating the flag.

The trial puts the project restriction inside an `OFFSET 0` subquery. This prevents PostgreSQL from pushing substring matching into the global trigram index. It streams the project's base rows once, then joins enterprise metadata for matching rows. The count and page use the same source and filters. No migration is required.

This is a workload-dependent tradeoff: globally common terms can require expensive trigram posting-list reads, while globally rare terms can be much faster through that index than through a large project scan. Keep the flag disabled by default and compare a small project cohort with a control before expanding it.

Validate both count and ordered pages for case-insensitive and multi-term searches, empty results, legacy project scope, hidden/stale/verified filters, tags, and pagination boundaries. Compare `EXPLAIN (ANALYZE, BUFFERS)` for count plus page with alternating baseline and trial runs across small and large projects, selective and common terms, and warm and cold cache conditions. Record PostgreSQL version and cache limitations. In the canary, compare endpoint p50/p95, error rates, database time and read blocks by project size and search type; roll back the flag if latency or database load regresses.
