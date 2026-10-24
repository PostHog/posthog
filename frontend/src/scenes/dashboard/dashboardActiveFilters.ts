import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'

import { BreakdownFilter, CompareFilter, DashboardFilter } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, IntervalType } from '~/types'

/** A dashboard-wide override that the filter bar shows as a removable chip. */
export type DashboardActiveFilter =
    | { kind: 'property'; index: number; filter: AnyPropertyFilter }
    | { kind: 'breakdown'; breakdownFilter: BreakdownFilter }
    | { kind: 'interval'; interval: IntervalType }
    | { kind: 'testAccounts'; filterTestAccounts: boolean }
    | { kind: 'compare'; compareFilter: CompareFilter }

/** True when the breakdown filter names something to break down by. The breakdown picker can write an empty object. */
export function hasBreakdown(breakdownFilter: BreakdownFilter | null | undefined): breakdownFilter is BreakdownFilter {
    if (!breakdownFilter) {
        return false
    }
    const { breakdown, breakdowns } = breakdownFilter
    const hasSingle = Array.isArray(breakdown) ? breakdown.length > 0 : breakdown != null && breakdown !== ''
    return hasSingle || (breakdowns?.length ?? 0) > 0
}

/**
 * The overrides that are in force, in the order the bar shows them. The date range and the
 * dashboard variables stay visible on the bar at all times, so they are not in this list.
 */
export function getDashboardActiveFilters(filters: DashboardFilter): DashboardActiveFilter[] {
    const active: DashboardActiveFilter[] = []
    ;(filters.properties ?? []).forEach((filter, index) => {
        if (isValidPropertyFilter(filter)) {
            active.push({ kind: 'property', index, filter })
        }
    })
    if (hasBreakdown(filters.breakdown_filter)) {
        active.push({ kind: 'breakdown', breakdownFilter: filters.breakdown_filter })
    }
    if (filters.interval) {
        active.push({ kind: 'interval', interval: filters.interval })
    }
    if (filters.filterTestAccounts != null) {
        active.push({ kind: 'testAccounts', filterTestAccounts: filters.filterTestAccounts })
    }
    if (filters.compareFilter != null) {
        active.push({ kind: 'compare', compareFilter: filters.compareFilter })
    }
    return active
}

export function breakdownFilterLabel(breakdownFilter: BreakdownFilter): string {
    const { breakdown, breakdowns } = breakdownFilter
    const properties = breakdowns?.length
        ? breakdowns.map(({ property }) => property)
        : Array.isArray(breakdown)
          ? breakdown
          : breakdown != null
            ? [breakdown]
            : []
    return `Breakdown: ${properties.map(String).join(', ')}`
}

export function intervalFilterLabel(interval: IntervalType): string {
    return `Grouped by ${interval}`
}

export function testAccountsFilterLabel(filterTestAccounts: boolean): string {
    return filterTestAccounts ? 'Test accounts filtered out' : 'Test accounts included'
}

export function compareFilterLabel(compareFilter: CompareFilter): string {
    if (!compareFilter.compare) {
        return 'No comparison'
    }
    return compareFilter.compare_to ? `Compared to ${compareFilter.compare_to}` : 'Compared to previous period'
}

/** The breakdown picker can write an object with no breakdown in it. The dashboard stores that as no breakdown. */
export function normalizeDashboardBreakdownFilter(breakdownFilter: BreakdownFilter | null): BreakdownFilter | null {
    if (breakdownFilter && !breakdownFilter.breakdown_type && !breakdownFilter.breakdowns) {
        return null
    }
    return breakdownFilter
}
