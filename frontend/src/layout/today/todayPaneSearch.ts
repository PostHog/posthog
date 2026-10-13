import { VIEW_TYPES, ViewTypeInfo } from 'scenes/views/viewsUtils'

export function matchesPaneQuery(label: string, query: string): boolean {
    const needle = query.trim().toLowerCase()
    return needle === '' || label.toLowerCase().includes(needle)
}

// A shorter search, like "da", matches too many words to mean a view type.
const VIEW_TYPE_SEARCH_MIN_LENGTH = 3

export function viewTypesForPaneSearch(search: string): ViewTypeInfo[] {
    const query = search.trim().toLowerCase()
    if (query.length < VIEW_TYPE_SEARCH_MIN_LENGTH) {
        return []
    }
    // The second check catches a search that wraps the type name, like "my dashboards".
    return VIEW_TYPES.filter(
        (info) => matchesPaneQuery(info.pluralLabel, query) || query.includes(info.label.toLowerCase())
    )
}
