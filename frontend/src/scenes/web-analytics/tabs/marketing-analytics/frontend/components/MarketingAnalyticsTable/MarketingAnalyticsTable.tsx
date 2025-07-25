import { useActions } from 'kea'
import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { webAnalyticsDataTableQueryContext } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import { DraftConversionGoalControls } from './DraftConversionGoalControls'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import { DataTableNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

export type MarketingAnalyticsTableProps = {
    query: DataTableNode
    insightProps: InsightLogicProps
}

export const MarketingAnalyticsTable = ({ query, insightProps }: MarketingAnalyticsTableProps): JSX.Element => {
    const { setQuery } = useActions(marketingAnalyticsTableLogic)

    // Create custom context with sortable headers for marketing analytics
    const marketingAnalyticsContext: QueryContext = {
        ...webAnalyticsDataTableQueryContext,
        insightProps,
    }

    return (
        <div className="bg-surface-primary">
            <div className="p-4 border-b border-border bg-bg-light">
                <DraftConversionGoalControls />
            </div>
            <div className="relative marketing-analytics-table-container">
                <Query
                    query={query}
                    readOnly={false}
                    context={marketingAnalyticsContext}
                    columnFeatures={[ColumnFeature.canSort]}
                    setQuery={setQuery}
                />
            </div>
        </div>
    )
}
