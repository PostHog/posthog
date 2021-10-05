// must keep separately from utils.ts, as that will make a cyclic import -> funnelLogic.ts -> utils.tsx -> funnelLogic.ts
import { Entity, FilterType, FunnelVizType, PropertyFilter, ViewType } from '~/types'

export const defaultFilterTestAccounts = (): boolean => {
    return localStorage.getItem('default_filter_test_accounts') === 'true' || false
}

interface UrlParams {
    insight: string
    properties: PropertyFilter[] | undefined
    filter_test_accounts: boolean
    funnel_viz_type?: string
    display?: string
    events?: Entity[]
    actions?: Entity[]
}

export function getInsightUrl(
    filters: Partial<FilterType>,
    hashParams: Record<string, any>,
    insightId?: number
): [string, Record<string, any>, Record<string, any>, { replace: true }] {
    const urlParams: UrlParams = {
        insight: filters.insight || 'TRENDS',
        properties: filters.properties,
        filter_test_accounts: defaultFilterTestAccounts(),
        events: (filters.events || []) as Entity[],
        actions: (filters.actions || []) as Entity[],
    }
    if (filters.insight === ViewType.FUNNELS) {
        urlParams.funnel_viz_type = FunnelVizType.Steps
        urlParams.display = 'FunnelViz'
    }
    const { q: _q, fromItem: otherFromItem, ...otherHashParams } = hashParams
    return [
        `/insights`,
        {},
        { q: urlParams, ...otherHashParams, fromItem: insightId || otherFromItem },
        { replace: true },
    ]
}
