import { useValues } from 'kea'

import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { FunnelStep, TrendResult } from '~/types'

import { resultsBreakdownLogic } from './resultsBreakdownLogic'

export const ResultsBreakdownContent = ({
    children,
}: {
    children?: (query: InsightVizNode, breakdownResults: FunnelStep[] | FunnelStep[][] | TrendResult[]) => JSX.Element
}): JSX.Element | null => {
    const { query, breakdownResults } = useValues(resultsBreakdownLogic)

    if (!query || !breakdownResults) {
        return null
    }

    return children && typeof children === 'function' ? children(query, breakdownResults) : null
}
