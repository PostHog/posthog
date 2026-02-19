import './MarketingAnalyticsTableStyleOverride.scss'

import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconGear, IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

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
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import { rowMatchesSearch } from '../../logic/utils'
import { MarketingAnalyticsCell } from '../../shared'
import {
    MarketingAnalyticsValidationWarningBanner,
    validateConversionGoals,
} from '../MarketingAnalyticsValidationWarningBanner'
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
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)

    const [searchTerm, setSearchTerm] = useState('')

    const validationWarnings = useMemo(() => validateConversionGoals(conversion_goals), [conversion_goals])

    const marketingAnalyticsContext: QueryContext = useMemo(
        () => ({
            ...webAnalyticsDataTableQueryContext,
            insightProps,
            columnFeatures: [ColumnFeature.canSort, ColumnFeature.canRemove, ColumnFeature.canPin],
            rowProps: (record: unknown) => {
                if (!rowMatchesSearch(record, searchTerm)) {
                    return { style: { display: 'none' } }
                }
                return {}
            },
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
        }),
        [insightProps, query.source, searchTerm]
    )

    return (
        <div className="bg-surface-primary">
            <div className="p-4 border-b border-border bg-bg-light">
                <div className="flex gap-4 justify-between items-center">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search campaigns..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                            className="w-64"
                            data-attr="marketing-analytics-search"
                        />
                        <Tooltip title="Filters the currently loaded results" delayMs={0}>
                            <IconInfo className="text-xl text-secondary" />
                        </Tooltip>
                    </div>
                    <LemonButton type="secondary" icon={<IconGear />} onClick={showColumnConfigModal}>
                        Configure columns
                    </LemonButton>
                </div>
            </div>
            {validationWarnings && validationWarnings.length > 0 && (
                <div className="pt-2">
                    <MarketingAnalyticsValidationWarningBanner warnings={validationWarnings} />
                </div>
            )}
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
