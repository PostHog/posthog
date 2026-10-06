import './MarketingAnalyticsTableStyleOverride.scss'

import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { Suspense, useId, useMemo, useState } from 'react'

import { IconGear, IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { DashboardModalLoading } from 'scenes/dashboard/DashboardModalLoading'
import { teamLogic } from 'scenes/teamLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsConstants,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { MarketingAnalyticsFreshness } from '~/scenes/marketing-analytics/MarketingAnalyticsFreshness'
import { MarketingAnalyticsNotReady } from '~/scenes/marketing-analytics/MarketingAnalyticsNotReady'
import { useMarketingAnalyticsPrecompute } from '~/scenes/marketing-analytics/useMarketingAnalyticsPrecompute'
import { webAnalyticsDataTableQueryContext } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { InsightLogicProps } from '~/types'

import {
    conversionRecordingsRequest,
    conversionRecordingsTableQuery,
    restoreConversionRecordingsColumns,
} from 'products/marketing_analytics/frontend/conversionRecordingsRequest'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import { rowMatchesSearch } from '../../logic/utils'
import { MarketingAnalyticsCell } from '../../shared'
import {
    MarketingAnalyticsValidationWarningBanner,
    validateConversionGoals,
} from '../MarketingAnalyticsValidationWarningBanner'
import { AdLevelInfoBanner } from './AdLevelInfoBanner'
import { MarketingAnalyticsColumnConfigModal } from './MarketingAnalyticsColumnConfigModal'

// The modal pulls in the recordings playlist and player, so keep it off the dashboard and events eager paths.
const ConversionRecordingsModal = lazyWithRetry(() =>
    import('products/marketing_analytics/frontend/ConversionRecordingsModal').then((module) => ({
        default: module.ConversionRecordingsModal,
    }))
)

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
    const { setQuery, setConversionRecordings } = useActions(marketingAnalyticsTableLogic)
    const { conversionRecordings } = useValues(marketingAnalyticsTableLogic)
    const { currentTeamId } = useValues(teamLogic)
    const tableId = useId()
    const tableKey = `${currentTeamId}:${tableId}`
    const { showColumnConfigModal, setDrillDownLevel } = useActions(marketingAnalyticsLogic)
    const { drillDownLevel, nativeSourcesHierarchyStatus } = useValues(marketingAnalyticsLogic)
    const hasExtendedDrillDown = useFeatureFlag('MARKETING_ANALYTICS_EXTENDED_DRILL_DOWN')
    const hasConversionRecordings = useFeatureFlag('MARKETING_ANALYTICS_CONVERSION_RECORDINGS')
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)

    const [searchTerm, setSearchTerm] = useState('')
    const recordings = conversionRecordings?.tableKey === tableKey ? conversionRecordings : null
    const tableQuery = useMemo(
        () => conversionRecordingsTableQuery(query, !!hasConversionRecordings && !isSharedView()),
        [query, hasConversionRecordings]
    )
    const { notReady: precomputeNotReady, computedAt } = useMarketingAnalyticsPrecompute(
        tableQuery.source,
        insightProps
    )

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
            columns: (() => {
                const allGroupingAliases = Object.values(MARKETING_ANALYTICS_DRILL_DOWN_CONFIG).map(
                    (c) => c.columnAlias
                )
                // Include every column the backend could ever return, not just the current select.
                // When drill-down level changes, stale response data lingers in kea-cached state
                // briefly; without a render fn for those stale columns, cells fall through to the
                // raw JSON viewer. We register render functions for:
                //   - all base columns (ID, Cost, Clicks, …)
                //   - all grouping aliases (Channel, Medium, Ad group, …)
                //   - all configured conversion goals + their "Cost per" variants — these are
                //     dynamic per team and only exist in some levels, so they're the most likely
                //     to flash through during a level switch
                //   - the current select (covers draft conversion goals and any ad-hoc columns)
                const conversionGoalColumns = conversion_goals.flatMap((goal) => [
                    goal.conversion_goal_name,
                    `${MarketingAnalyticsConstants.CostPer} ${goal.conversion_goal_name}`,
                ])
                const allKnownColumns = new Set<string>([
                    ...Object.values(MarketingAnalyticsBaseColumns),
                    ...allGroupingAliases,
                    ...conversionGoalColumns,
                    ...((query.source as MarketingAnalyticsTableQuery).select ?? []),
                ])
                const draftConversionGoal = (query.source as MarketingAnalyticsTableQuery).draftConversionGoal
                const drillDownGoals = draftConversionGoal
                    ? [draftConversionGoal, ...conversion_goals]
                    : conversion_goals
                return Array.from(allKnownColumns).reduce(
                    (acc, column) => {
                        const isGroupingColumn = allGroupingAliases.includes(column)
                        const goal = drillDownGoals.find((goal) => goal.conversion_goal_name === column)
                        acc[column] = {
                            render: (props) => {
                                const cell = (
                                    <MarketingAnalyticsCell
                                        {...props}
                                        style={{
                                            maxWidth: isGroupingColumn ? '200px' : undefined,
                                        }}
                                    />
                                )
                                const value = (props.value as MarketingAnalyticsItem | null)?.value
                                const request =
                                    hasConversionRecordings &&
                                    !isSharedView() &&
                                    goal &&
                                    goal.kind !== 'DataWarehouseNode' &&
                                    typeof value === 'number' &&
                                    value > 0
                                        ? conversionRecordingsRequest(
                                              (props.query as DataTableNode).source as MarketingAnalyticsTableQuery,
                                              props.record,
                                              goal.conversion_goal_id
                                          )
                                        : null
                                return request && goal ? (
                                    <LemonButton
                                        type="tertiary"
                                        fullWidth
                                        className="[&_.cursor-default]:cursor-pointer"
                                        data-attr="marketing-analytics-conversion-recordings"
                                        tooltip="View recordings of these conversion sessions"
                                        onClick={() =>
                                            setConversionRecordings({
                                                tableKey,
                                                request,
                                                goalName: goal.conversion_goal_name,
                                            })
                                        }
                                    >
                                        {cell}
                                    </LemonButton>
                                ) : (
                                    cell
                                )
                            },
                        }
                        return acc
                    },
                    {} as Record<string, QueryContextColumn>
                )
            })(),
        }),
        [
            insightProps,
            query.source,
            searchTerm,
            conversion_goals,
            hasConversionRecordings,
            tableKey,
            setConversionRecordings,
        ]
    )

    return (
        <div className="bg-surface-primary">
            {recordings && (
                <Suspense fallback={<DashboardModalLoading isOpen onClose={() => setConversionRecordings(null)} />}>
                    <ConversionRecordingsModal {...recordings} onClose={() => setConversionRecordings(null)} />
                </Suspense>
            )}
            <div className="p-4 border-b border-border bg-bg-light">
                <div className="flex flex-wrap gap-4 justify-between items-center">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                            className="w-64"
                            data-attr="marketing-analytics-search"
                        />
                        <LemonSelect
                            value={drillDownLevel}
                            onChange={(value) => value && setDrillDownLevel(value)}
                            options={[
                                {
                                    title: 'Platform',
                                    options: [
                                        {
                                            value: MarketingAnalyticsDrillDownLevel.Channel,
                                            label: 'Channel',
                                        },
                                        {
                                            value: MarketingAnalyticsDrillDownLevel.ChannelSource,
                                            label: 'Channel + Source',
                                        },
                                        {
                                            value: MarketingAnalyticsDrillDownLevel.Source,
                                            label: 'Source',
                                        },
                                        {
                                            value: MarketingAnalyticsDrillDownLevel.Campaign,
                                            label: 'Campaign',
                                        },
                                    ],
                                },
                                ...(hasExtendedDrillDown
                                    ? [
                                          {
                                              title: 'UTM',
                                              options: [
                                                  {
                                                      value: MarketingAnalyticsDrillDownLevel.Medium,
                                                      label: 'Medium',
                                                  },
                                                  {
                                                      value: MarketingAnalyticsDrillDownLevel.Content,
                                                      label: 'Content',
                                                  },
                                                  {
                                                      value: MarketingAnalyticsDrillDownLevel.Term,
                                                      label: 'Term',
                                                  },
                                              ],
                                          },
                                          {
                                              title: 'Ad level',
                                              options: [
                                                  {
                                                      value: MarketingAnalyticsDrillDownLevel.AdGroup,
                                                      label: 'Ad group',
                                                  },
                                                  {
                                                      value: MarketingAnalyticsDrillDownLevel.Ad,
                                                      label: 'Ad',
                                                  },
                                              ],
                                          },
                                      ]
                                    : []),
                            ]}
                            size="small"
                        />
                        <Tooltip title="Filters the currently loaded results" delayMs={0}>
                            <IconInfo className="text-xl text-secondary" />
                        </Tooltip>
                    </div>
                    <div className="flex items-center gap-2">
                        <MarketingAnalyticsFreshness computedAt={computedAt} />
                        <LemonButton type="secondary" icon={<IconGear />} onClick={showColumnConfigModal}>
                            Configure columns
                        </LemonButton>
                    </div>
                </div>
            </div>
            {validationWarnings && validationWarnings.length > 0 && (
                <div className="pt-2">
                    <MarketingAnalyticsValidationWarningBanner warnings={validationWarnings} />
                </div>
            )}
            {(drillDownLevel === MarketingAnalyticsDrillDownLevel.AdGroup ||
                drillDownLevel === MarketingAnalyticsDrillDownLevel.Ad) && (
                <div className="pt-2 px-2">
                    <AdLevelInfoBanner
                        drillDownLevel={drillDownLevel}
                        sourcesHierarchyStatus={nativeSourcesHierarchyStatus}
                    />
                </div>
            )}
            {precomputeNotReady ? (
                <div className="p-4">
                    <MarketingAnalyticsNotReady />
                </div>
            ) : (
                <div className="relative marketing-analytics-table-container">
                    <Query
                        attachTo={attachTo}
                        query={tableQuery}
                        readOnly={false}
                        context={marketingAnalyticsContext}
                        setQuery={(updated) =>
                            setQuery(
                                tableQuery === query ? updated : restoreConversionRecordingsColumns(updated, query)
                            )
                        }
                    />
                </div>
            )}
            <MarketingAnalyticsColumnConfigModal query={query} />
        </div>
    )
}
