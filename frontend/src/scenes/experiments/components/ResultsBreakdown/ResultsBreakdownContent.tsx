import { useValues } from 'kea'

import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { FunnelStep, TrendResult } from '~/types'

import { ExploreAsInsightButton } from './ExploreAsInsightButton'
import { resultsBreakdownLogic } from './resultsBreakdownLogic'
import { ResultsQuery } from './ResultsQuery'

export const ResultsBreakdownContent = ({
    children,
}: {
    children?: (query: InsightVizNode, breakdownResults: FunnelStep[] | FunnelStep[][] | TrendResult[]) => JSX.Element
}): JSX.Element | null => {
    const { query, breakdownResults } = useValues(resultsBreakdownLogic)

    if (!query || !breakdownResults) {
        return null
    }

    return children ? (
        children(query, breakdownResults)
    ) : (
        <div>
            <div className="flex justify-end">
                <ExploreAsInsightButton query={query} />
            </div>
            <div className="pb-4">
                <ResultsQuery query={query} results={breakdownResults} />
            </div>
        </div>
    )
}
