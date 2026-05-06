import './MarketingAnalyticsTableStyleOverride.scss'

import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconGear, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

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
    const { showColumnConfigModal, setDrillDownLevel } = useActions(marketingAnalyticsLogic)
    const { drillDownLevel } = useValues(marketingAnalyticsLogic)
    const hasDrillDown = useFeatureFlag('MARKETING_ANALYTICS_DRILL_DOWN')
    const hasExtendedDrillDown = useFeatureFlag('MARKETING_ANALYTICS_EXTENDED_DRILL_DOWN')
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
                return Array.from(allKnownColumns).reduce(
                    (acc, column) => {
                        const isGroupingColumn = allGroupingAliases.includes(column)
                        acc[column] = {
                            render: (props) => (
                                <MarketingAnalyticsCell
                                    {...props}
                                    style={{
                                        maxWidth: isGroupingColumn ? '200px' : undefined,
                                    }}
                                />
                            ),
                        }
                        return acc
                    },
                    {} as Record<string, QueryContextColumn>
                )
            })(),
        }),
        [insightProps, query.source, searchTerm, conversion_goals]
    )

    return (
        <div className="bg-surface-primary">
            <div className="p-4 border-b border-border bg-bg-light">
                <div className="flex gap-4 justify-between items-center">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                            className="w-64"
                            data-attr="marketing-analytics-search"
                        />
                        {hasDrillDown && (
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
                        )}
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
            {(drillDownLevel === MarketingAnalyticsDrillDownLevel.AdGroup ||
                drillDownLevel === MarketingAnalyticsDrillDownLevel.Ad) && (
                <div className="pt-2 px-2">
                    <LemonBanner type="info" dismissKey="marketing-analytics-ad-level-info">
                        Ad group and ad metrics come directly from your ad platform. Conversion goals aren't shown at
                        this level because events can't be attributed to a specific ad. Make sure the ad group and ad
                        tables are enabled in your source sync settings to see data here.
                    </LemonBanner>
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
