import { useActions } from 'kea'
import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { webAnalyticsDataTableQueryContext } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import { DraftConversionGoalControls } from './DraftConversionGoalControls'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import { DataTableNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'
import { MarketingAnalyticsColumnConfigModal } from './MarketingAnalyticsColumnConfigModal'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconGear } from '@posthog/icons'
import './MarketingAnalyticsTableStyleOverride.scss'
import { humanFriendlyNumber } from 'lib/utils'

// Generic cell renderer function that handles marketing analytics data
const renderMarketingAnalyticsCell = (value: any): JSX.Element | null => {
    if (!value) {
        return <span>-</span>
    }

    if (!Array.isArray(value)) {
        return <span>{String(value)}</span>
    }

    const [current, previous] = value as [number, number]

    const formatValue = (num: number | null): string => {
        if (num === null || num === undefined) {
            return '-'
        }
        return humanFriendlyNumber(num)
    }

    const currentFormatted = formatValue(current)
    const previousFormatted = formatValue(previous)

    return (
        <div className="flex flex-wrap gap-2">
            <div className="w-full">{currentFormatted}</div>
            <div className="w-full text-muted">
                {previous !== null && previous !== undefined ? previousFormatted : '-'}
            </div>
        </div>
    )
}

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
        columnFeatures: [ColumnFeature.canSort, ColumnFeature.canRemove],
        cellRenderer: renderMarketingAnalyticsCell,
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
