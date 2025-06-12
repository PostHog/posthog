import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { FunnelStep, TrendResult } from '~/types'

export type ResultBreakdownRenderProps = {
    query: InsightVizNode | null
    breakdownResults: FunnelStep[] | FunnelStep[][] | TrendResult[] | null
}
