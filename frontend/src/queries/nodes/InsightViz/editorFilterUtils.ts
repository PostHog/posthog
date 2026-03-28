import { InsightEditorFilter } from '~/types'

/** An InsightEditorFilter with an optional `show` field. When `show` is false, null, or undefined, the filter is excluded. */
export type ConditionalEditorFilter = InsightEditorFilter & { show?: boolean | null }

/** Returns only filters where `show` is not explicitly false, null, or undefined. */
export function visibleFilters(filters: ConditionalEditorFilter[]): InsightEditorFilter[] {
    return filters
        .filter((f) => !('show' in f) || (f.show !== false && f.show !== null && f.show !== undefined))
        .map(({ show: _show, ...rest }) => rest)
}
