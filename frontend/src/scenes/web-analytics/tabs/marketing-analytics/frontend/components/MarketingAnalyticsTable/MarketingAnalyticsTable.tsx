import { useActions } from 'kea'
import { Query } from '~/queries/Query/Query'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { webAnalyticsDataTableQueryContext } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import { DraftConversionGoalControls } from './DraftConversionGoalControls'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import {
    DataTableNode,
    MARKETING_ANALYTICS_SCHEMA,
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'
import { MarketingAnalyticsColumnConfigModal } from './MarketingAnalyticsColumnConfigModal'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconGear } from '@posthog/icons'
import './MarketingAnalyticsTableStyleOverride.scss'
import { renderMarketingAnalyticsCell } from '../../shared'

export type MarketingAnalyticsTableProps = {
    query: DataTableNode
    insightProps: InsightLogicProps
}

export const MarketingAnalyticsTable = ({ query, insightProps }: MarketingAnalyticsTableProps): JSX.Element => {
    const { setQuery } = useActions(marketingAnalyticsTableLogic)
    const { showColumnConfigModal } = useActions(marketingAnalyticsLogic)

    // Filter out columns that are not numbers because they can't be compared between periods
    const nonNumberColumns = Object.keys(MARKETING_ANALYTICS_SCHEMA).filter(
        (column) => !MARKETING_ANALYTICS_SCHEMA[column as MarketingAnalyticsColumnsSchemaNames].type.includes('number')
    )

    // Create custom context with sortable headers for marketing analytics
    const marketingAnalyticsContext: QueryContext = {
        ...webAnalyticsDataTableQueryContext,
        insightProps,
        columnFeatures: [ColumnFeature.canSort, ColumnFeature.canRemove],
        columns: (query.source as MarketingAnalyticsTableQuery).select
            ?.filter((column) => !nonNumberColumns.includes(column))
            .reduce(
                (acc, column) => {
                    acc[column] = {
                        title: column,
                        render: (props) => renderMarketingAnalyticsCell(props.value),
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
