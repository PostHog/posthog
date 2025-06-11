import { useValues } from 'kea'

import { ExploreAsInsightButton } from './ExploreAsInsightButton'
import { resultsBreakdownLogic } from './resultsBreakdownLogic'
import { ResultsQuery } from './ResultsQuery'

export const ResultsBreakdownContent = (): JSX.Element | null => {
    const { query, breakdownResults } = useValues(resultsBreakdownLogic)

    if (!query || !breakdownResults) {
        return null
    }

    return (
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
