import './CalendarHeatMap.scss'

import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { CalendarHeatmapQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { WebActiveHoursHeatmap } from '../WebActiveHoursHeatmap/WebActiveHoursHeatmap'

interface CalendarHeatMapProps {
    context?: QueryContext
}

export function InsightCalendarHeatMapContainer({ context }: CalendarHeatMapProps): JSX.Element | null {
    const { insightProps, query } = useValues(insightLogic)
    return (
        <WebActiveHoursHeatmap
            context={{ ...context, insightProps: insightProps }}
            query={(query as InsightVizNode)?.source as CalendarHeatmapQuery}
        />
    )
}
