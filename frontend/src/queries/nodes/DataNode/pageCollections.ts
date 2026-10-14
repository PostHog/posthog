const pageCollectionIds = new Set<string>()

export function pageCollectionId(id: string): string {
    pageCollectionIds.add(id)
    return id
}

export function isPageCollection(id: string): boolean {
    return pageCollectionIds.has(id)
}
