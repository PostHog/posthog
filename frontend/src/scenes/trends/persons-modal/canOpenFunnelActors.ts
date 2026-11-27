import type { FunnelsFilter } from '~/queries/schema/schema-general'

export function canOpenFunnelActors(filter: FunnelsFilter | null | undefined): boolean {
    const aggregateBy = filter?.funnelAggregateByHogQL
    return !filter?.customAggregationTarget && (!aggregateBy || aggregateBy === 'properties.$session_id')
}
