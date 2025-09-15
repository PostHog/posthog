// scenes/dashboard/TileFiltersOverride.tsx
import { BindLogic, useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import type { DashboardTile, InsightLogicProps, QueryBasedInsightModel } from '~/types'

import { tileLogic } from './tileLogic'

export function TileFiltersOverride({
    tile,
    dashboardId,
}: {
    tile: DashboardTile<QueryBasedInsightModel>
    dashboardId: number
}): JSX.Element {
    const { overrides, hasOverrides } = useValues(tileLogic)
    const { setDates, setProperties, setBreakdown, resetOverrides } = useActions(tileLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const insightProps: InsightLogicProps = {
        dashboardItemId: tile.insight?.short_id,
        dashboardId: dashboardId,
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
        <div className="space-y-4">
            <div>
                <p className="text-sm text-muted mb-4">
                    Set custom filters for this tile that will override the dashboard's global filters.
                </p>
            </div>

            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium mb-2 block">Date Range</label>
                    <DateFilter
                        showCustom
                        dateFrom={overrides.date_from ?? null}
                        dateTo={overrides.date_to ?? null}
                        onChange={(from, to) => setDates(from, to)}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar />
                                <span className="hide-when-small"> {key}</span>
                            </>
                        )}
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
                    <BindLogic logic={insightLogic} props={insightProps}>
                        <TaxonomicBreakdownFilter
                            insightProps={insightProps}
                            breakdownFilter={overrides.breakdown_filter ?? null}
                            isTrends={false}
                            showLabel={false}
                            updateBreakdownFilter={(breakdown_filter: BreakdownFilter) => {
                                if (
                                    !breakdown_filter.breakdown &&
                                    !breakdown_filter.breakdowns &&
                                    !breakdown_filter.breakdown_type
                                ) {
                                    setBreakdown(null)
                                } else {
                                    setBreakdown(breakdown_filter)
                                }
                            }}
                            updateDisplay={() => {}}
                            disablePropertyInfo
                            size="small"
                        />
                    </BindLogic>
                </div>
            </div>

            {hasOverrides && (
                <>
                    <LemonDivider />
                    <div className="flex justify-end">
                        <LemonButton type="secondary" onClick={resetOverrides} size="small">
                            Clear All Overrides
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
