import { ANALYTICS_TYPES, AnalyticsTypeInfo } from 'scenes/analytics/analyticsUtils'

export function matchesPaneQuery(label: string, query: string): boolean {
    const needle = query.trim().toLowerCase()
    return needle === '' || label.toLowerCase().includes(needle)
}

// A shorter search, like "da", matches too many words to mean an analytics type.
const ANALYTICS_TYPE_SEARCH_MIN_LENGTH = 3

export function analyticsTypesForPaneSearch(search: string): AnalyticsTypeInfo[] {
    const query = search.trim().toLowerCase()
    if (query.length < ANALYTICS_TYPE_SEARCH_MIN_LENGTH) {
        return []
    }
    // The second check catches a search that wraps the type name, like "my dashboards".
    return ANALYTICS_TYPES.filter(
        (info) => matchesPaneQuery(info.pluralLabel, query) || query.includes(info.label.toLowerCase())
    )
}
