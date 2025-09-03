import { useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { timeZoneLabel } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { CalendarHeatMap } from 'scenes/web-analytics/CalendarHeatMap/CalendarHeatMap'

import { ChartParams } from '~/types'

import { calendarHeatMapLogic } from './calendarHeatMapLogic'
import {
    AggregationLabel,
    getColumnAggregationTooltip,
    getDataTooltip,
    getOverallAggregationTooltip,
    getRowAggregationTooltip,
    thresholdFontSize,
} from './utils'

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function TrendsCalendarHeatMap(_props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { processedData, rowLabels, columnLabels } = useValues(calendarHeatMapLogic(insightProps))
    const { timezone } = useValues(teamLogic)
    const offset = dayjs().tz(timezone).utcOffset() / 60

    return (
        <>
            <LemonBanner
                type="info"
                dismissKey="calendar-heatmap-beta-banner"
                className="mb-2"
                action={{ children: 'Send feedback', id: 'calendar-heatmap-feedback-button' }}
            >
                Calendar heatmap display is in beta. Please let us know what you'd like to see here and/or report any
                issues directly to us!
            </LemonBanner>
            <CalendarHeatMap
                isLoading={false}
                thresholdFontSize={thresholdFontSize}
                rowLabels={rowLabels}
                columnLabels={columnLabels}
                getRowAggregationTooltip={getRowAggregationTooltip}
                allAggregationsLabel={AggregationLabel.All}
                processedData={processedData}
                getDataTooltip={getDataTooltip}
                getColumnAggregationTooltip={getColumnAggregationTooltip}
                getOverallAggregationTooltip={getOverallAggregationTooltip}
                showColumnAggregations={true}
                showRowAggregations={true}
            />
            <div className="flex items-center justify-center gap-2 text-muted text-xs mt-2">
                <span>Data shown in timezone: {timeZoneLabel(timezone, offset)}</span>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    to={urls.settings('environment', 'date-and-time')}
                    targetBlank={false}
                >
                    Change
                </LemonButton>
            </div>
        </>
    )
}
