export type GroupRevenueSource = 'revenue-analytics' | 'properties' | null

export interface GroupRevenueValue {
    value: number | null
    source: GroupRevenueSource
}

export interface GroupRevenue {
    mrr: GroupRevenueValue
    lifetimeValue: GroupRevenueValue
}

export interface GroupRevenueAnalyticsRow {
    mrr: number | null
    lifetimeValue: number | null
}

function resolveValue(analyticsValue: number | null | undefined, propertyValue: unknown): GroupRevenueValue {
    if (analyticsValue !== null && analyticsValue !== undefined) {
        return { value: analyticsValue, source: 'revenue-analytics' }
    }
    if (typeof propertyValue === 'number' && !isNaN(propertyValue)) {
        return { value: propertyValue, source: 'properties' }
    }
    return { value: null, source: null }
}

// Revenue analytics is the preferred source. The `mrr` and `customer_lifetime_value` group properties
// cover teams that set revenue on the group themselves, which matches the group page.
export function resolveGroupRevenue(
    analyticsRow: GroupRevenueAnalyticsRow | undefined,
    groupProperties: Record<string, any> | undefined
): GroupRevenue {
    return {
        mrr: resolveValue(analyticsRow?.mrr, groupProperties?.mrr),
        lifetimeValue: resolveValue(analyticsRow?.lifetimeValue, groupProperties?.customer_lifetime_value),
    }
}
