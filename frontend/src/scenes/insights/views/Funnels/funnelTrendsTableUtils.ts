import { hasBreakdown } from 'scenes/funnels/funnelUtils'

import { FunnelsActorsQuery, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { BreakdownKeyType } from '~/types'

export interface FunnelTrendsActorsQueryParams {
    source: FunnelsQuery
    /** Already-formatted entrance period start (the clicked period's own date, shifted for previous). */
    entrancePeriodStart: string
    breakdownValue?: BreakdownKeyType
    /** The clicked row's period. `'previous'` makes the runner scope actors to the shifted window. */
    compare?: 'current' | 'previous'
}

/** Builds the actors query for a clicked trends-table cell.
 *
 * In compare mode each row belongs to one period, so we thread `compare` through: the runner
 * resolves `'previous'` to the shifted date range, mirroring `openPersonsModalForSeries`. Without
 * it, a previous-period click would resolve against the current window and return no actors. */
export function buildFunnelTrendsActorsQuery({
    source,
    entrancePeriodStart,
    breakdownValue,
    compare,
}: FunnelTrendsActorsQueryParams): FunnelsActorsQuery {
    return {
        kind: NodeKind.FunnelsActorsQuery,
        source,
        funnelTrendsDropOff: false,
        includeRecordings: true,
        funnelTrendsEntrancePeriodStart: entrancePeriodStart,
        ...(hasBreakdown(breakdownValue) ? { funnelStepBreakdown: breakdownValue } : {}),
        ...(compare ? { compare } : {}),
    }
}
