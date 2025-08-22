import './MarketingAnalyticsTableStyleOverride.scss'

import { useActions } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode, MarketingAnalyticsTableQuery } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { webAnalyticsDataTableQueryContext } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { InsightLogicProps } from '~/types'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import { MarketingAnalyticsCell } from '../../shared'
import { DraftConversionGoalControls } from './DraftConversionGoalControls'
import { MarketingAnalyticsColumnConfigModal } from './MarketingAnalyticsColumnConfigModal'

export type MarketingAnalyticsTableProps = {
    query: DataTableNode
    insightProps: InsightLogicProps
}

export const MarketingAnalyticsTable = ({ query, insightProps }: MarketingAnalyticsTableProps): JSX.Element => {
    const { setQuery } = useActions(marketingAnalyticsTableLogic)
    const { showColumnConfigModal } = useActions(marketingAnalyticsLogic)

    // Create custom context with sortable headers for marketing analytics
    const marketingAnalyticsContext: QueryContext = {
        ...webAnalyticsDataTableQueryContext,
        insightProps,
        columnFeatures: [ColumnFeature.canSort, ColumnFeature.canRemove, ColumnFeature.canPin],
        columns: (query.source as MarketingAnalyticsTableQuery).select?.reduce(
            (acc, column) => {
                acc[column] = {
                    title: column,
                    render: MarketingAnalyticsCell,
                }
                return acc
            },
            {} as Record<string, QueryContextColumn>
        ),
    }

    return (
        <div className="bg-surface-primary">
            <div className="p-4 border-b border-border bg-bg-light">
                <div className="flex gap-4">
                    <div className="flex-1">
                        <DraftConversionGoalControls />
                    </div>
                    <div className="self-start">
                        <LemonButton type="secondary" icon={<IconGear />} onClick={showColumnConfigModal}>
                            Configure columns
                        </LemonButton>
                    </div>
                </div>
            </div>
            <div className="relative marketing-analytics-table-container">
                <Query query={query} readOnly={false} context={marketingAnalyticsContext} setQuery={setQuery} />
            </div>
            <MarketingAnalyticsColumnConfigModal query={query} />
        </div>
    )
}
