// scenes/dashboard/TileFiltersOverride.tsx
import './TileFiltersOverride.scss'

import { BindLogic, useActions, useValues } from 'kea'

import { IconCalendar, IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSegmentedButton, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { isInsightQueryWithBreakdown, isInsightQueryWithSeries, isInsightVizNode } from '~/queries/utils'
import type { DashboardTile, InsightLogicProps, IntervalType, QueryBasedInsightModel } from '~/types'

import { tileLogic } from './tileLogic'

type TestAccountFilterChoice = 'inherit' | 'filter-out' | 'include'

const CHOICE_TO_FILTER: Record<TestAccountFilterChoice, boolean | null> = {
    inherit: null,
    'filter-out': true,
    include: false,
}

const CHOICE_HINTS: Record<TestAccountFilterChoice, string> = {
    inherit: "Uses the dashboard's setting, or the insight's own if the dashboard doesn't set one.",
    'filter-out': 'Internal and test users are filtered out of this insight.',
    include: 'Internal and test users are included in this insight.',
}

export function TileFiltersOverride({ tile }: { tile: DashboardTile<QueryBasedInsightModel> }): JSX.Element {
    const { overrides } = useValues(tileLogic)
    const { setDates, setProperties, setBreakdown, setInterval, setFilterTestAccounts, setIgnoreDashboardFilters } =
        useActions(tileLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { currentTeam } = useValues(teamLogic)

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const query = tile.insight?.query
    const querySource = isInsightVizNode(query) ? query.source : query
    const supportsInterval = isInsightQueryWithSeries(querySource ?? undefined)
    const supportsBreakdown = isInsightQueryWithBreakdown(querySource)

    const filterTestAccounts = overrides.filterTestAccounts ?? null
    const testAccountChoice: TestAccountFilterChoice =
        filterTestAccounts === null ? 'inherit' : filterTestAccounts ? 'filter-out' : 'include'
    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0

    // The breakdown picker needs a mounted insightLogic. Bind a throwaway one, like DashboardEditBar,
    // keyed per tile so it can't collide with the edit bar's `dashboardItemId: 'new'` binding.
    const breakdownInsightProps: InsightLogicProps = {
        dashboardItemId: `new-tile-override-${tile.id}`,
        cachedInsight: null,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [],
            },
        },
    }

    return (
        <div className="space-y-4 tile-filters-override">
            <div>
                <p className="text-sm text-muted mb-4">
                    Set custom filters for this tile. Property filters apply on top of the dashboard's, while the tile's
                    date range, interval, breakdown, and test account filtering replace the dashboard's.
                </p>
            </div>

            <div>
                <LemonDivider label="Scope" />
                <div className="flex flex-col gap-4 pb-4">
                    <div>
                        <LemonSwitch
                            checked={!!overrides.ignoreDashboardFilters}
                            onChange={setIgnoreDashboardFilters}
                            label="Ignore dashboard filters"
                            bordered
                            fullWidth
                            data-attr="tile-ignore-dashboard-filters"
                        />
                        <p className="text-xs text-muted mt-1 mb-0">
                            When on, none of the dashboard's filters apply to this insight. The overrides below still
                            do.
                        </p>
                    </div>
                </div>

                <LemonDivider label="Time" />
                <div className="flex flex-col gap-4 pb-4">
                    <div>
                        <label className="text-sm font-medium mb-2 block">Date range</label>
                        <DateFilter
                            showCustom
                            showExplicitDateToggle
                            dateFrom={overrides.date_from ?? null}
                            dateTo={overrides.date_to ?? null}
                            explicitDate={overrides.explicitDate}
                            onChange={(from, to, explicitDate) => setDates(from, to, explicitDate)}
                            makeLabel={(key) => (
                                <>
                                    <IconCalendar />
                                    <span className="hide-when-small"> {key}</span>
                                </>
                            )}
                        />
                    </div>

                    <div>
                        <label className="text-sm font-medium mb-2 block">Interval</label>
                        <LemonSelect<IntervalType | null>
                            size="small"
                            value={overrides.interval ?? null}
                            dropdownMatchSelectWidth={false}
                            disabledReason={
                                supportsInterval ? undefined : "This insight type doesn't support an interval override"
                            }
                            onChange={(interval) => setInterval(interval)}
                            options={[
                                { value: null, label: 'inherit' },
                                { value: 'hour', label: 'hour' },
                                { value: 'day', label: 'day' },
                                { value: 'week', label: 'week' },
                                { value: 'month', label: 'month' },
                            ]}
                            data-attr="tile-override-interval"
                        />
                    </div>
                </div>

                <LemonDivider label="Filters" />
                <div className="flex flex-col gap-4 pb-4">
                    <div>
                        <label className="text-sm font-medium mb-2 block">Properties</label>
                        <PropertyFilters
                            onChange={(properties) => setProperties(properties)}
                            pageKey={`tile_${tile.id}_properties`}
                            propertyFilters={overrides.properties ?? []}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.EventFeatureFlags,
                                TaxonomicFilterGroupType.EventMetadata,
                                ...(hasPageview ? [TaxonomicFilterGroupType.PageviewUrls] : []),
                                ...(hasScreen ? [TaxonomicFilterGroupType.Screens] : []),
                                TaxonomicFilterGroupType.EmailAddresses,
                                ...groupsTaxonomicTypes,
                                TaxonomicFilterGroupType.Cohorts,
                                TaxonomicFilterGroupType.Elements,
                                TaxonomicFilterGroupType.SessionProperties,
                                TaxonomicFilterGroupType.HogQLExpression,
                                TaxonomicFilterGroupType.DataWarehousePersonProperties,
                            ]}
                        />
                    </div>

                    <div>
                        <div className="flex items-center gap-1 mb-2">
                            <label className="text-sm font-medium">Test account filtering</label>
                            <LemonButton
                                icon={<IconGear />}
                                size="xsmall"
                                noPadding
                                to={urls.settings('project-product-analytics', 'internal-user-filtering')}
                                tooltip="Configure internal and test account filters"
                            />
                        </div>
                        <LemonSegmentedButton<TestAccountFilterChoice>
                            size="small"
                            value={testAccountChoice}
                            onChange={(next) => setFilterTestAccounts(CHOICE_TO_FILTER[next])}
                            options={[
                                {
                                    value: 'inherit',
                                    label: 'Inherit',
                                    tooltip: "Use the dashboard's setting, or the insight's own",
                                    'data-attr': 'tile-test-account-filter-inherit',
                                },
                                {
                                    value: 'filter-out',
                                    label: 'Filter out',
                                    tooltip: 'Force test account filtering on for this insight',
                                    disabledReason: !hasTestAccountFilters
                                        ? "You haven't set any internal test filters. Click the gear icon to configure."
                                        : undefined,
                                    'data-attr': 'tile-test-account-filter-out',
                                },
                                {
                                    value: 'include',
                                    label: 'Include',
                                    tooltip: 'Force test account filtering off for this insight',
                                    'data-attr': 'tile-test-account-filter-include',
                                },
                            ]}
                        />
                        <p className="text-xs text-muted mt-1 mb-0">{CHOICE_HINTS[testAccountChoice]}</p>
                    </div>
                </div>

                <LemonDivider label="Display" />
                <div className="flex flex-col gap-4 pb-4">
                    <div>
                        <label className="text-sm font-medium mb-2 block">Breakdown</label>
                        <BindLogic logic={insightLogic} props={breakdownInsightProps}>
                            <TaxonomicBreakdownFilter
                                insightProps={breakdownInsightProps}
                                breakdownFilter={overrides.breakdown_filter}
                                isTrends={false}
                                isFunnels={false}
                                showLabel={false}
                                disabledReason={
                                    supportsBreakdown
                                        ? undefined
                                        : "This insight type doesn't support a breakdown override"
                                }
                                updateBreakdownFilter={(breakdown_filter) => {
                                    let newBreakdownFilter: BreakdownFilter | null = breakdown_filter
                                    // taxonomicBreakdownFilterLogic can generate an empty breakdown_filter object
                                    if (
                                        breakdown_filter &&
                                        !breakdown_filter.breakdown_type &&
                                        !breakdown_filter.breakdowns
                                    ) {
                                        newBreakdownFilter = null
                                    }
                                    setBreakdown(newBreakdownFilter)
                                }}
                                updateDisplay={() => {}}
                                disablePropertyInfo
                                size="small"
                            />
                        </BindLogic>
                    </div>
                </div>
            </div>
        </div>
    )
}
