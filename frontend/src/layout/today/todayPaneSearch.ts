export function matchesPaneQuery(label: string, query: string): boolean {
    const needle = query.trim().toLowerCase()
    return needle === '' || label.toLowerCase().includes(needle)
}
