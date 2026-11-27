// A DataTable with a default sort is controlled, and a controlled DataTable leaves the row order to its caller.
export function sortQuillTableRows<T>(
    rows: T[],
    sorting: { id: string; desc: boolean }[],
    sorters: Record<string, ((a: T, b: T) => number) | undefined>
): T[] {
    const active = sorting[0]
    const sorter = active ? sorters[active.id] : undefined
    if (!active || !sorter) {
        return rows
    }
    const sorted = [...rows].sort(sorter)
    return active.desc ? sorted.reverse() : sorted
}
