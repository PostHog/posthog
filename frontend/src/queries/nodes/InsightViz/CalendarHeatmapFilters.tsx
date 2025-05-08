import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { CalendarHeatmapQuery } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { FilterType } from '~/types'

import { actionsAndEventsToSeries, FilterTypeActionsAndEvents } from '../InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'

export function CalendarHeatmapFilters(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const filters = queryNodeToFilter(querySource)
    const mathAvailability = MathAvailability.CalendarHeatmapOnly

    return (
        <ActionFilter
            filters={filters}
            setFilters={(payload: Partial<FilterType>): void => {
                updateQuerySource({
                    series: actionsAndEventsToSeries(payload as FilterTypeActionsAndEvents, true, mathAvailability),
                } as CalendarHeatmapQuery)
            }}
            typeKey={keyForInsightLogicProps('new')(insightProps)}
            showSeriesIndicator
            showNestedArrow
            entitiesLimit={1}
            mathAvailability={mathAvailability}
            hideDeleteBtn={true}
        />
    )
}
