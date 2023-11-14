import { useValues, useActions } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { FilterType } from '~/types'
import { alphabet } from 'lib/utils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { TrendsQuery, FunnelsQuery, LifecycleQuery, StickinessQuery } from '~/queries/schema'
import { isInsightQueryNode } from '~/queries/utils'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { actionsAndEventsToSeries } from '../InsightQuery/utils/filtersToQueryNode'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

export function TrendsSeries(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, isTrends, isLifecycle, isStickiness, display, hasFormula } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const propertiesTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(isTrends ? [TaxonomicFilterGroupType.Sessions] : []),
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const filters = queryNodeToFilter(querySource)

    return (
        <>
            {isLifecycle && (
                <div className="leading-6">
                    Showing <b>Unique users</b> who did
                </div>
            )}
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => {
                    updateQuerySource({ series: actionsAndEventsToSeries(payload as any) } as
                        | TrendsQuery
                        | FunnelsQuery
                        | StickinessQuery
                        | LifecycleQuery)
                }}
                typeKey={`${keyForInsightLogicProps('new')(insightProps)}-TrendsSeries`}
                buttonCopy={`Add graph ${hasFormula ? 'variable' : 'series'}`}
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    (display && SINGLE_SERIES_DISPLAY_TYPES.includes(display) && !hasFormula) || isLifecycle
                        ? 1
                        : alphabet.length
                }
                mathAvailability={
                    isLifecycle
                        ? MathAvailability.None
                        : isStickiness
                        ? MathAvailability.ActorsOnly
                        : MathAvailability.All
                }
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
            />
        </>
    )
}
