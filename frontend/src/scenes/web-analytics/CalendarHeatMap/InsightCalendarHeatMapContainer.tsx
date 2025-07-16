import './CalendarHeatMap.scss'

import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { CalendarHeatmapQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { WebActiveHoursHeatmap } from '../WebActiveHoursHeatmap/WebActiveHoursHeatmap'
import { LemonBanner } from '@posthog/lemon-ui'

interface CalendarHeatMapProps {
    context?: QueryContext
}

export function InsightCalendarHeatMapContainer({ context }: CalendarHeatMapProps): JSX.Element | null {
    const { insightProps, query } = useValues(insightLogic)
    return (
        <>
            <LemonBanner
                type="info"
                dismissKey="calendar-heatmap-beta-banner"
                className="mb-2"
                action={{ children: 'Send feedback', id: 'calendar-heatmap-feedback-button' }}
            >
                Calendar heatmap insight is in beta. Please let us know what you'd like to see here and/or report any
                issues directly to us!
            </LemonBanner>
            <WebActiveHoursHeatmap
                context={{ ...context, insightProps: insightProps }}
                query={(query as InsightVizNode)?.source as CalendarHeatmapQuery}
            />
        </>
    )
}
