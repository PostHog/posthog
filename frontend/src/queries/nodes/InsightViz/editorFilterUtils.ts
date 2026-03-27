import { InsightEditorFilter } from '~/types'

export function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e): e is InsightEditorFilter => !!e)
}

/** An InsightEditorFilter with an optional `show` field. When `show` is false or null, the filter is excluded. */
export type ConditionalEditorFilter = InsightEditorFilter & { show?: boolean | null }

/** Returns only filters where `show` is not explicitly false or null. */
export function visibleFilters(filters: ConditionalEditorFilter[]): InsightEditorFilter[] {
    return filters.filter((f) => f.show !== false && f.show !== null).map(({ show: _show, ...rest }) => rest)
}
