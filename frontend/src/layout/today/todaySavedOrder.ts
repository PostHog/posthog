/** Puts the rows a person dragged in their saved order. A row they never dragged keeps its own slot in `rows`. */
export function applySavedOrder<T>(rows: T[], order: string[], keyOf: (row: T) => string): T[] {
    const rank = new Map(order.map((key, index) => [key, index]))
    const dragged = rows
        .filter((row) => rank.has(keyOf(row)))
        .sort((first, second) => (rank.get(keyOf(first)) ?? 0) - (rank.get(keyOf(second)) ?? 0))
    let next = 0
    return rows.map((row) => (rank.has(keyOf(row)) ? dragged[next++] : row))
}

/** The keys after a drop moves `key` to the place of `overKey`, or null when the drop changes nothing. */
export function movedKeys(keys: string[], key: string, overKey: string): string[] | null {
    const from = keys.indexOf(key)
    const to = keys.indexOf(overKey)
    if (from < 0 || to < 0 || from === to) {
        return null
    }
    const next = [...keys]
    next.splice(to, 0, ...next.splice(from, 1))
    return next
}
