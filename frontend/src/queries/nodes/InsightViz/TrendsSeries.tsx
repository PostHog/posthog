import { useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { alphabet } from 'lib/utils'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { AggregationSelect } from 'scenes/insights/filters/AggregationSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { groupsModel } from '~/models/groupsModel'
import { FunnelsQuery, LifecycleQuery, StickinessQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { ChartDisplayType, FilterType } from '~/types'

import { actionsAndEventsToSeries } from '../InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'

export function TrendsSeries(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, isTrends, isLifecycle, isStickiness, display, hasFormula, series } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const { showGroupsOptions: showGroupsOptionsFromModel, groupsTaxonomicTypes } = useValues(groupsModel)

    // Disable groups for calendar heatmap
    const showGroupsOptions = display === ChartDisplayType.CalendarHeatmap ? false : showGroupsOptionsFromModel

    const propertiesTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.EventMetadata,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.SessionProperties,
        TaxonomicFilterGroupType.HogQLExpression,
        TaxonomicFilterGroupType.DataWarehouseProperties,
        TaxonomicFilterGroupType.DataWarehousePersonProperties,
    ]

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const filters = queryNodeToFilter(querySource)
    const mathAvailability = isLifecycle
        ? MathAvailability.None
        : isStickiness
          ? MathAvailability.ActorsOnly
          : display === ChartDisplayType.CalendarHeatmap
            ? MathAvailability.CalendarHeatmapOnly
            : MathAvailability.All

    return (
        <>
            {isLifecycle && (
                <div className="leading-6">
                    <div className="flex items-center">
                        Showing
                        {showGroupsOptions ? (
                            <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                        ) : (
                            <b> Unique users </b>
                        )}
                        who did
                    </div>
                </div>
            )}
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => {
                    updateQuerySource({ series: actionsAndEventsToSeries(payload as any, true, mathAvailability) } as
                        | TrendsQuery
                        | FunnelsQuery
                        | StickinessQuery
                        | LifecycleQuery)
                }}
                typeKey={keyForInsightLogicProps('new')(insightProps)}
                buttonCopy={`Add graph ${hasFormula ? 'variable' : 'series'}`}
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    (display && SINGLE_SERIES_DISPLAY_TYPES.includes(display) && !hasFormula) || isLifecycle
                        ? 1
                        : alphabet.length
                }
                mathAvailability={mathAvailability}
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                actionsTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    ...(isTrends && display !== ChartDisplayType.CalendarHeatmap
                        ? [TaxonomicFilterGroupType.DataWarehouse]
                        : []),
                ]}
                hideDeleteBtn={series?.length === 1}
                addFilterDocLink="https://posthog.com/docs/product-analytics/trends/filters"
            />
        </>
    )
}
