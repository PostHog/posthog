// Registration, not inference: a per-entity id such as a trace or a chart must never reach
// `collection_key`, so a page-level container declares itself by wrapping its id here.
const pageCollectionIds = new Set<string>()

/** Marks a collection id as a page-level container whose load cycle is worth timing. */
export function pageCollectionId(id: string): string {
    pageCollectionIds.add(id)
    return id
}

export function isPageCollection(id: string): boolean {
    return pageCollectionIds.has(id)
}
