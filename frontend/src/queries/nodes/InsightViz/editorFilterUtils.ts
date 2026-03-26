import { pluralize } from 'lib/utils'

import { BreakdownFilter } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, InsightEditorFilter, PropertyGroupFilter } from '~/types'

export function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e): e is InsightEditorFilter => !!e)
}

export function getFiltersSummary(
    properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined | null
): string | null {
    if (!properties) {
        return null
    }
    const filters: AnyPropertyFilter[] = Array.isArray(properties)
        ? properties
        : properties.values.flatMap((group) => group.values.filter((v): v is AnyPropertyFilter => 'key' in v))
    if (filters.length === 0) {
        return null
    }
    const names = filters.map((f) => ('key' in f && f.key ? String(f.key) : null)).filter(Boolean)
    return names.length > 0 ? names.join(', ') : pluralize(filters.length, 'filter')
}

export function getBreakdownSummary(breakdownFilter: BreakdownFilter | null | undefined): string | null {
    if (!breakdownFilter) {
        return null
    }
    const breakdowns = breakdownFilter.breakdowns
    if (breakdowns?.length) {
        const names = breakdowns.map((b) => b.property).filter(Boolean)
        return names.length > 0 ? names.join(', ') : null
    }
    if (breakdownFilter.breakdown) {
        const bd = breakdownFilter.breakdown
        if (typeof bd === 'string') {
            return bd
        }
        const count = Array.isArray(bd) ? bd.length : 1
        return pluralize(count, 'breakdown')
    }
    return null
}

export function getSeriesSummary(
    series: { custom_name?: string; name?: string; event?: string | null }[] | null | undefined
): string | null {
    if (!series || series.length === 0) {
        return null
    }
    const names = series.map((s) => s.custom_name || ('event' in s && s.event) || s.name).filter(Boolean)
    return names.length > 0 ? names.join(', ') : pluralize(series.length, 'series')
}
