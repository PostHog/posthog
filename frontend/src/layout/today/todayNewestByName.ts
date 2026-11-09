/**
 * Keeps the first `limit` items of a newest-first list, then sorts them by name, so a click on a row does not move it.
 * `id` breaks ties: without it, two rows with the same name swap places when one is opened.
 */
export function newestByName<T>(items: T[], name: (item: T) => string, id: (item: T) => string, limit: number): T[] {
    return items
        .slice(0, limit)
        .sort(
            (first, second) =>
                name(first).localeCompare(name(second), undefined, { sensitivity: 'base', numeric: true }) ||
                id(first).localeCompare(id(second))
        )
}
