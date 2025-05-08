import './CalendarHeatMap.scss'

import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { EventsHeatMapQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { WebActiveHoursHeatmap } from '../WebActiveHoursHeatmap/WebActiveHoursHeatmap'

interface EventsHeatMapProps {
    context?: QueryContext
}

export function EventsHeatMapContainer({ context }: EventsHeatMapProps): JSX.Element | null {
    const { query } = useValues(insightLogic)
    return <WebActiveHoursHeatmap context={context} query={query as EventsHeatMapQuery} />
}
