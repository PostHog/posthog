import './CalendarHeatMap.scss'

import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { QueryContext } from '~/queries/types'
import { CalendarHeatmapQuery } from '~/schema'

import { WebActiveHoursHeatmap } from '../WebActiveHoursHeatmap/WebActiveHoursHeatmap'

interface CalendarHeatMapProps {
    context?: QueryContext
}

export function InsightCalendarHeatMapContainer({ context }: CalendarHeatMapProps): JSX.Element | null {
    const { insightProps, query } = useValues(insightLogic)
    return (
        <WebActiveHoursHeatmap
            context={{ ...context, insightProps: insightProps }}
            query={(insightProps.query || query) as CalendarHeatmapQuery}
        />
    )
}
