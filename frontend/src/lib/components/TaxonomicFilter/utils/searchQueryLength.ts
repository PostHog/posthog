/**
 * The search endpoints reject a query past their cap with a 400. They measure the raw `search`
 * parameter with Python `len()`, which counts code points, and they measure it before they strip
 * it. Measure the same string the picker sends, the same way, so this guard and the endpoint agree
 * on where the boundary sits.
 */
export function isSearchQueryTooLong(searchQuery: string, maxSearchQueryLength: number): boolean {
    if (maxSearchQueryLength <= 0) {
        return false
    }

    return Array.from(searchQuery).length > maxSearchQueryLength
}
