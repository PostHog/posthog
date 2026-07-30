// scenes/dashboard/TileFiltersOverride.tsx
import './TileFiltersOverride.scss'

import { BindLogic, useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { isInsightQueryWithBreakdown, isInsightQueryWithSeries, isInsightVizNode } from '~/queries/utils'
import type { DashboardTile, InsightLogicProps, IntervalType, QueryBasedInsightModel } from '~/types'

import { tileLogic } from './tileLogic'

export function TileFiltersOverride({ tile }: { tile: DashboardTile<QueryBasedInsightModel> }): JSX.Element {
    const { overrides } = useValues(tileLogic)
    const { setDates, setProperties, setBreakdown, setInterval, setIgnoreDashboardFilters } = useActions(tileLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const query = tile.insight?.query
    const querySource = isInsightVizNode(query) ? query.source : query
    const supportsInterval = isInsightQueryWithSeries(querySource ?? undefined)
    const supportsBreakdown = isInsightQueryWithBreakdown(querySource)

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
                    date range, interval, and breakdown replace the dashboard's.
                </p>
            </div>

            <div className="space-y-4">
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
                        When on, none of the dashboard's filters apply to this insight. The overrides below still do.
                    </p>
                </div>

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
                    <label className="text-sm font-medium mb-2 block">Breakdown</label>
                    <BindLogic logic={insightLogic} props={breakdownInsightProps}>
                        <TaxonomicBreakdownFilter
                            insightProps={breakdownInsightProps}
                            breakdownFilter={overrides.breakdown_filter}
                            isTrends={false}
                            isFunnels={false}
                            showLabel={false}
                            disabledReason={
                                supportsBreakdown ? undefined : "This insight type doesn't support a breakdown override"
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
    )
}
