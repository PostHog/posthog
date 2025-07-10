import type { InsightVizNode } from '~/schema'
import type { FunnelStep, TrendResult } from '~/types'

export type ResultBreakdownRenderProps = {
    query: InsightVizNode | null
    breakdownResultsLoading: boolean
    breakdownResults: FunnelStep[] | FunnelStep[][] | TrendResult[] | null
    exposureDifference: number
}
