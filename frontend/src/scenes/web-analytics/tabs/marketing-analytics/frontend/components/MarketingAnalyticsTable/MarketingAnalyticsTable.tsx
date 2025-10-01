import './MarketingAnalyticsTableStyleOverride.scss'

import { BuiltLogic, LogicWrapper, useActions } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import {
    DataTableNode,
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
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
    attachTo?: LogicWrapper | BuiltLogic
}

export const MarketingAnalyticsTable = ({
    query,
    insightProps,
    attachTo,
}: MarketingAnalyticsTableProps): JSX.Element => {
    const { setQuery } = useActions(marketingAnalyticsTableLogic)
    const { showColumnConfigModal } = useActions(marketingAnalyticsLogic)

    const handleIncludeAllConversionsChange = (checked: boolean): void => {
        const sourceQuery = query.source as MarketingAnalyticsTableQuery
        setQuery({
            ...query,
            source: {
                ...sourceQuery,
                includeAllConversions: checked,
            },
        })
    }

    // Create custom context with sortable headers for marketing analytics
    const marketingAnalyticsContext: QueryContext = {
        ...webAnalyticsDataTableQueryContext,
        insightProps,
        columnFeatures: [ColumnFeature.canSort, ColumnFeature.canRemove, ColumnFeature.canPin],
        columns: (query.source as MarketingAnalyticsTableQuery).select?.reduce(
            (acc, column) => {
                acc[column] = {
                    title: column,
                    render: (props) => (
                        <MarketingAnalyticsCell
                            {...props}
                            style={{
                                maxWidth:
                                    column.toLocaleLowerCase() ===
                                    MarketingAnalyticsColumnsSchemaNames.Campaign.toLocaleLowerCase()
                                        ? '200px'
                                        : undefined,
                            }}
                        />
                    ),
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
                    <div className="self-start flex flex-col gap-2">
                        <LemonButton type="secondary" icon={<IconGear />} onClick={showColumnConfigModal}>
                            Configure columns
                        </LemonButton>
                        <LemonSwitch
                            checked={(query.source as MarketingAnalyticsTableQuery).includeAllConversions ?? false}
                            onChange={handleIncludeAllConversionsChange}
                            label="Show organic conversions"
                            tooltip="Show conversion goal rows even when they don't match any campaign data from integrations"
                            size="small"
                        />
                    </div>
                </div>
            </div>
            <div className="relative marketing-analytics-table-container">
                <Query
                    attachTo={attachTo}
                    query={query}
                    readOnly={false}
                    context={marketingAnalyticsContext}
                    setQuery={setQuery}
                />
            </div>
            <MarketingAnalyticsColumnConfigModal query={query} />
        </div>
    )
}
