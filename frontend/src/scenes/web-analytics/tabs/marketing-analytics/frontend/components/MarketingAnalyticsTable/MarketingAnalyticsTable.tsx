import './MarketingAnalyticsTableStyleOverride.scss'

import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconGear, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

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

import { marketingAnalyticsLogic, NativeSourceHierarchyStatus } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import { nativeSourceDisplayLabel, rowMatchesSearch } from '../../logic/utils'
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
    const { drillDownLevel, nativeSourcesHierarchyStatus } = useValues(marketingAnalyticsLogic)
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
                    <AdLevelInfoBanner
                        drillDownLevel={drillDownLevel}
                        sourcesHierarchyStatus={nativeSourcesHierarchyStatus}
                    />
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

type AdLevelInfoBannerProps = {
    drillDownLevel: MarketingAnalyticsDrillDownLevel
    sourcesHierarchyStatus: NativeSourceHierarchyStatus[]
}

/** Empty-state banner shown at AD_GROUP / AD drill-down. Distinguishes three states
 * per source:
 * 1. Fully syncing → won't show in any list (already appearing in the table).
 * 2. Sync-fixable → schemas exist in the platform's data import but the user hasn't
 *    enabled them. Calls each one out with a deep-link to the sync settings tab so
 *    they can flip the toggle without hunting. The link carries `ph_utm_source=ma`
 *    for attribution.
 * 3. Platform-unsupported → the data import pipeline doesn't yet sync the resource
 *    at all (e.g. LinkedIn creatives at AD level). No link, just a heads-up so the
 *    user understands it's not their misconfiguration.
 */
const AdLevelInfoBanner = ({ drillDownLevel, sourcesHierarchyStatus }: AdLevelInfoBannerProps): JSX.Element => {
    const { refreshSourcesForBanner } = useActions(marketingAnalyticsLogic)
    const isAdGroup = drillDownLevel === MarketingAnalyticsDrillDownLevel.AdGroup
    const fixableSources = sourcesHierarchyStatus.filter((s) =>
        isAdGroup ? !s.supportsAdGroup && !s.adGroupUnsupported : !s.supportsAd && !s.adUnsupported
    )
    const platformUnsupportedSources = sourcesHierarchyStatus.filter((s) =>
        isAdGroup ? s.adGroupUnsupported : s.adUnsupported
    )
    const dismissKey = isAdGroup ? 'marketing-analytics-ad-group-level-info' : 'marketing-analytics-ad-level-info'
    const hasGaps = fixableSources.length > 0 || platformUnsupportedSources.length > 0

    // The "fix it" link opens settings in a new tab. When the user returns here
    // after enabling the missing schemas, the banner state is stale until we
    // re-fetch sources. Refresh on visibility-change so the gaps disappear
    // automatically — scoped to "has fixable gaps right now" so we don't burn
    // an API call every time the user alt-tabs once the banner is green.
    const skipFirstVisibilityCall = useRef(true)
    const hasFixableSources = fixableSources.length > 0
    usePageVisibilityCb((isVisible) => {
        if (skipFirstVisibilityCall.current) {
            skipFirstVisibilityCall.current = false
            return
        }
        if (isVisible && hasFixableSources) {
            refreshSourcesForBanner({ reloadTilesAfter: true })
        }
    })

    return (
        <LemonBanner type={fixableSources.length > 0 ? 'warning' : 'info'} dismissKey={dismissKey}>
            <div>
                Ad group and ad metrics come directly from your ad platform. Conversion goals aren't shown at this level
                because events can't be attributed to a specific ad.
            </div>
            {fixableSources.length > 0 && (
                <div className="mt-2">
                    <div className="font-semibold">
                        {fixableSources.length === 1
                            ? 'One source needs more schemas synced to appear here:'
                            : 'These sources need more schemas synced to appear here:'}
                    </div>
                    <ul className="mt-1 list-disc pl-5">
                        {fixableSources.map((source) => {
                            const missing = isAdGroup ? source.missingForAdGroup : source.missingForAd
                            return (
                                <li key={source.sourceId}>
                                    <Link
                                        to={`${urls.dataWarehouseSource(`managed-${source.sourceId}`)}?ph_utm_source=ma`}
                                        target="_blank"
                                    >
                                        {nativeSourceDisplayLabel(source.sourceType)}
                                    </Link>
                                    : enable{' '}
                                    {missing.map((schema, idx) => (
                                        <span key={schema}>
                                            <code>{schema}</code>
                                            {idx < missing.length - 1 ? ', ' : ''}
                                        </span>
                                    ))}
                                </li>
                            )
                        })}
                    </ul>
                </div>
            )}
            {platformUnsupportedSources.length > 0 && (
                <div className="mt-2">
                    {platformUnsupportedSources.map((s) => nativeSourceDisplayLabel(s.sourceType)).join(', ')}{' '}
                    {platformUnsupportedSources.length === 1 ? "doesn't" : "don't"} yet expose{' '}
                    {isAdGroup ? 'ad-group' : 'ad'}-level data through PostHog's data warehouse import — coming in a
                    follow-up.
                </div>
            )}
            {!hasGaps && (
                <div className="mt-2">
                    Make sure the ad group and ad tables are enabled in your source sync settings to see data here.
                </div>
            )}
        </LemonBanner>
    )
}
