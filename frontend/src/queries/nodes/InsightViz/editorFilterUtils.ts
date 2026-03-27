import { InsightEditorFilter } from '~/types'

export function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e): e is InsightEditorFilter => !!e)
}

/** An InsightEditorFilter with an optional `show` field. When `show` is false, the filter is excluded. */
export type ConditionalEditorFilter = InsightEditorFilter & { show?: boolean }

/** Returns only filters where `show` is not explicitly false. */
export function visibleFilters(filters: ConditionalEditorFilter[]): InsightEditorFilter[] {
    return filters.filter((f) => f.show !== false).map(({ show: _show, ...rest }) => rest)
}
