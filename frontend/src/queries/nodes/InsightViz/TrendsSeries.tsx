import { useValues, useActions } from 'kea'
// import { trendsLogic } from 'scenes/trends/trendsLogic'
import { groupsModel } from '~/models/groupsModel'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { InsightType, FilterType, InsightLogicProps } from '~/types'
import { alphabet } from 'lib/utils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { TrendsQuery, FunnelsQuery, LifecycleQuery, StickinessQuery } from '~/queries/schema'
import {
    isLifecycleQuery,
    isStickinessQuery,
    isTrendsQuery,
    isInsightQueryWithDisplay,
    isInsightQueryNode,
} from '~/queries/utils'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { actionsAndEventsToSeries } from '../InsightQuery/utils/filtersToQueryNode'

import { getDisplay } from './utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

type TrendsSeriesProps = {
    insightProps: InsightLogicProps
}

export function TrendsSeries({ insightProps }: TrendsSeriesProps): JSX.Element | null {
    const dataLogic = insightVizDataLogic(insightProps)
    const { querySource } = useValues(dataLogic)
    const { updateQuerySource } = useActions(dataLogic)
    const { isFormulaOn } = useValues(trendsLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const propertiesTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(isTrendsQuery(querySource) ? [TaxonomicFilterGroupType.Sessions] : []),
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const display = getDisplay(querySource)
    const filters = queryNodeToFilter(querySource)

    return (
        <>
            {isLifecycleQuery(querySource) && (
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
                typeKey={`trends_${InsightType.TRENDS}_data_exploration`}
                buttonCopy={`Add graph ${isFormulaOn ? 'variable' : 'series'}`}
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    (isInsightQueryWithDisplay(querySource) &&
                        display &&
                        SINGLE_SERIES_DISPLAY_TYPES.includes(display) &&
                        !isFormulaOn) ||
                    isLifecycleQuery(querySource)
                        ? 1
                        : alphabet.length
                }
                mathAvailability={
                    isLifecycleQuery(querySource)
                        ? MathAvailability.None
                        : isStickinessQuery(querySource)
                        ? MathAvailability.ActorsOnly
                        : MathAvailability.All
                }
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
            />
        </>
    )
}
