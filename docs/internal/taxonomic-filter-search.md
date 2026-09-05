# Taxonomic filter search loading

The legacy picker and the rebuilt menu hold aggregated search results until the contributing categories settle. This prevents late category results from moving a choice under the pointer. Only categories offered by the picker contribute to that wait; a category-specific list waits for its own results.

Scoped property searches return properties associated with the selected events. A separate unscoped request counts matches across the project so the picker can offer an expansion to other properties.

The expansion count must not delay the scoped results or keep the aggregate reveal barrier closed. It can add an expansion option below the results after they appear. A failed count leaves the scoped results usable, and a count from an earlier search must not affect the current search. Expanding explicitly starts a full-results request and uses the normal list loading state.

The legacy implementation separates these requests in `infiniteListLogic.ts`; the rebuilt implementation uses independent resources in `hooks/useGroupList.ts`. Keep this behavior consistent across both implementations.
