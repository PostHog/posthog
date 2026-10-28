import './MarketingAnalyticsTableStyleOverride.scss'

import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { Suspense, useId, useMemo, useState } from 'react'

import { IconGear, IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { DashboardModalLoading } from 'scenes/dashboard/DashboardModalLoading'
import { teamLogic } from 'scenes/teamLogic'
import { TileId } from 'scenes/web-analytics/common'
import { WebTileHeader } from 'scenes/web-analytics/WebTileHeader'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsConstants,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { MarketingAnalyticsFreshness } from '~/scenes/marketing-analytics/MarketingAnalyticsFreshness'
import { MarketingAnalyticsNotReady } from '~/scenes/marketing-analytics/MarketingAnalyticsNotReady'
import { useMarketingAnalyticsPrecompute } from '~/scenes/marketing-analytics/useMarketingAnalyticsPrecompute'
import { webAnalyticsDataTableQueryContext } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { InsightLogicProps } from '~/types'

import { MetricSourceBadge } from 'products/marketing_analytics/frontend/components/MetricSourceBadge'
import {
    conversionRecordingsTableQuery,
    restoreConversionRecordingsColumns,
} from 'products/marketing_analytics/frontend/conversionRecordingsRequest'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import {
    MARKETING_TABLE_COLUMN_VIEWS,
    MarketingTableColumnView,
    activeColumnView,
    columnsForView,
    isPostHogColumn,
} from '../../logic/marketingTableColumnViews'
import { rowMatchesSearch } from '../../logic/utils'
import {
    MarketingAnalyticsValidationWarningBanner,
    validateConversionGoals,
} from '../MarketingAnalyticsValidationWarningBanner'
import { AdLevelInfoBanner } from './AdLevelInfoBanner'
import { MarketingAnalyticsColumnConfigModal } from './MarketingAnalyticsColumnConfigModal'
import {
    MarketingAnalyticsTableCell,
    MarketingAnalyticsTableCellContext,
    MarketingAnalyticsTableCellOptions,
} from './MarketingAnalyticsTableCell'

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
    const { conversionRecordings, defaultColumns } = useValues(marketingAnalyticsTableLogic)
    const { currentTeamId } = useValues(teamLogic)
    const tableId = useId()
    const tableKey = `${currentTeamId}:${tableId}`
    const { showColumnConfigModal, setDrillDownLevel } = useActions(marketingAnalyticsLogic)
    const { drillDownLevel, nativeSourcesHierarchyStatus, setupEnabled } = useValues(marketingAnalyticsLogic)
    const hasExtendedDrillDown = useFeatureFlag('MARKETING_ANALYTICS_EXTENDED_DRILL_DOWN')
    const hasConversionRecordings = useFeatureFlag('MARKETING_ANALYTICS_CONVERSION_RECORDINGS')
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)

    const [searchTerm, setSearchTerm] = useState('')
    const breakdownOptions = [
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
    ]
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

    // Custom is whatever no preset matches, or a preset someone chose to start editing from.
    const [customPicked, setCustomPicked] = useState(false)
    const presetView = activeColumnView((query.source as MarketingAnalyticsTableQuery).select, defaultColumns)
    const columnView: MarketingTableColumnView | 'custom' = customPicked || !presetView ? 'custom' : presetView
    const setColumnView = (view: MarketingTableColumnView | 'custom'): void => {
        setCustomPicked(view === 'custom')
        if (view !== 'custom') {
            setQuery({
                ...query,
                source: {
                    ...(query.source as MarketingAnalyticsTableQuery),
                    select: columnsForView(view, defaultColumns),
                },
            })
        }
    }

    // Rendered inside the DataTable toolbar, so Export shares one row with the table controls.
    const toolbar = useMemo(
        () => [
            <WebTileHeader
                key="title"
                className="min-h-0 p-0"
                tileId={TileId.MARKETING_CAMPAIGN_BREAKDOWN}
                titlePrefix="Performance metrics by"
                titleDropdown={{
                    value: drillDownLevel,
                    options: breakdownOptions.flatMap((group) => group.options),
                    onChange: (value) => setDrillDownLevel(value as MarketingAnalyticsDrillDownLevel),
                }}
            />,
            <LemonInput
                key="search"
                type="search"
                size="small"
                placeholder="Search..."
                value={searchTerm}
                onChange={setSearchTerm}
                className="w-56"
                data-attr="marketing-analytics-search"
            />,
            <Tooltip key="search-info" title="Search filters the loaded rows" delayMs={0}>
                <IconInfo className="text-xl text-secondary" />
            </Tooltip>,
            <div key="spacer" className="flex-1" />,
            <MarketingAnalyticsFreshness key="freshness" computedAt={computedAt} />,
            <LemonSegmentedButton
                key="column-view"
                size="small"
                value={columnView}
                onChange={setColumnView}
                options={[...MARKETING_TABLE_COLUMN_VIEWS, { value: 'custom' as const, label: 'Custom' }]}
                data-attr="marketing-analytics-column-view"
            />,
            ...(columnView === 'custom'
                ? [
                      <LemonButton
                          key="columns"
                          type="secondary"
                          size="small"
                          icon={<IconGear />}
                          onClick={showColumnConfigModal}
                      >
                          Configure columns
                      </LemonButton>,
                  ]
                : []),
        ],
        // eslint-disable-next-line react-hooks/exhaustive-deps -- setColumnView only closes over query and defaultColumns
        [computedAt, columnView, query, defaultColumns, showColumnConfigModal, drillDownLevel, searchTerm]
    )

    const marketingAnalyticsContext: QueryContext = useMemo(
        () => ({
            ...webAnalyticsDataTableQueryContext,
            dataTableStickyHeader: true,
            compactDataTableToolbar: true,
            dataTableToolbarClassName: 'pt-3',
            dataTableExportIconOnly: true,
            customActions: toolbar,
            insightProps,
            columnFeatures: [ColumnFeature.canSort, ColumnFeature.canRemove, ColumnFeature.canPin],
            rowProps: (record: unknown) => {
                if (!rowMatchesSearch(record, searchTerm)) {
                    return { style: { display: 'none' } }
                }
                return {}
            },
            columns: (() => {
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
                    ...Object.values(MARKETING_ANALYTICS_DRILL_DOWN_CONFIG).map((c) => c.columnAlias),
                    ...conversionGoalColumns,
                    ...((query.source as MarketingAnalyticsTableQuery).select ?? []),
                ])
                return Object.fromEntries(
                    Array.from(allKnownColumns, (column): [string, QueryContextColumn] => [
                        column,
                        {
                            render: MarketingAnalyticsTableCell,
                            title: isPostHogColumn(column) ? (
                                <span className="inline-flex items-center gap-1">
                                    {column}
                                    <MetricSourceBadge source="posthog" />
                                </span>
                            ) : undefined,
                        },
                    ])
                )
            })(),
        }),
        [insightProps, query.source, searchTerm, conversion_goals, toolbar]
    )

    const cellOptions: MarketingAnalyticsTableCellOptions = useMemo(
        () => ({
            conversionGoals: conversion_goals,
            tableKey,
            showConversionRecordings: !!hasConversionRecordings && !isSharedView(),
            setConversionRecordings,
        }),
        [conversion_goals, tableKey, hasConversionRecordings, setConversionRecordings]
    )

    return (
        <div className="border rounded bg-surface-primary">
            {recordings && (
                <Suspense fallback={<DashboardModalLoading isOpen onClose={() => setConversionRecordings(null)} />}>
                    <ConversionRecordingsModal {...recordings} onClose={() => setConversionRecordings(null)} />
                </Suspense>
            )}
            {!setupEnabled && validationWarnings && validationWarnings.length > 0 && (
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
                <div className="relative marketing-analytics-table-container px-3 pb-3">
                    <MarketingAnalyticsTableCellContext.Provider value={cellOptions}>
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
                    </MarketingAnalyticsTableCellContext.Provider>
                </div>
            )}
            <MarketingAnalyticsColumnConfigModal query={query} />
        </div>
    )
}
