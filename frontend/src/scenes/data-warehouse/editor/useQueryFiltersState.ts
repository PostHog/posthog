import { useActions, useMountedLogic, useValues } from 'kea'

import { isHogQLQuery } from '~/queries/schema/node-guards'
import type { HogQLFilters, HogQLQuery } from '~/queries/schema/schema-general'

import { sqlEditorLogic } from './sqlEditorLogic'

const hasDateRange = (filters?: HogQLFilters): boolean => {
    return !!(filters?.dateRange?.date_from || filters?.dateRange?.date_to)
}

const hasPropertyFilters = (filters?: HogQLFilters): boolean => {
    return !!filters?.properties?.length
}

const hasActiveFilters = (filters?: HogQLFilters): boolean => {
    return hasDateRange(filters) || hasPropertyFilters(filters) || !!filters?.filterTestAccounts
}

export const filtersTooltip = ({
    filtersMissingPlaceholder,
    bindingsMissingTimestamp,
    usesFiltersPlaceholder,
}: {
    filtersMissingPlaceholder: boolean
    bindingsMissingTimestamp: boolean
    usesFiltersPlaceholder: boolean
}): string | undefined => {
    if (filtersMissingPlaceholder) {
        return "Filters are present, but this SQL query doesn't include a {filters} tag"
    }
    if (bindingsMissingTimestamp) {
        return "This query's {filters(...)} bindings have no timestamp key, so it can't take a date filter"
    }
    if (!usesFiltersPlaceholder) {
        return 'Insert {filters} into your SQL query to apply filters'
    }
    return undefined
}

export interface QueryFiltersState {
    source: HogQLQuery
    hasFilters: boolean
    usesFiltersPlaceholder: boolean
    /** Filters are set, but the query has no {filters} placeholder to apply them. */
    filtersMissingPlaceholder: boolean
    /** The query binds its own {filters(...)} columns without a timestamp, so it can't take a date range. */
    bindingsMissingTimestamp: boolean
    tooltip: string | undefined
    setHogQLQuery: (query: HogQLQuery) => void
    resetFilters: () => void
    insertPlaceholder: () => void
}

/** The SQL editor's filters and what changing them does, shared by the Lemon menu and the quill popover. */
export function useQueryFiltersState(): QueryFiltersState | null {
    const { sourceQuery, hasFiltersPlaceholder, filtersPlaceholderBindings } = useValues(sqlEditorLogic)
    const { setSourceQuery, runQuery, insertTextAtCursor } = useActions(sqlEditorLogic)
    const logic = useMountedLogic(sqlEditorLogic)

    if (!isHogQLQuery(sourceQuery.source)) {
        return null
    }

    const source = sourceQuery.source
    const hasFilters = hasActiveFilters(source.filters)
    const usesFiltersPlaceholder = hasFiltersPlaceholder
    const filtersMissingPlaceholder = hasFilters && !usesFiltersPlaceholder
    const bindingsMissingTimestamp =
        filtersPlaceholderBindings !== null && !filtersPlaceholderBindings.includes('timestamp')

    const setHogQLQuery = (query: HogQLQuery): void => {
        setSourceQuery({ ...sourceQuery, source: query })
        if (usesFiltersPlaceholder) {
            runQuery(logic.values.queryInput ?? query.query)
        }
    }

    return {
        source,
        hasFilters,
        usesFiltersPlaceholder,
        filtersMissingPlaceholder,
        bindingsMissingTimestamp,
        tooltip: filtersTooltip({ filtersMissingPlaceholder, bindingsMissingTimestamp, usesFiltersPlaceholder }),
        setHogQLQuery,
        resetFilters: () => setHogQLQuery({ ...source, filters: {} }),
        insertPlaceholder: () => insertTextAtCursor('{filters}'),
    }
}
