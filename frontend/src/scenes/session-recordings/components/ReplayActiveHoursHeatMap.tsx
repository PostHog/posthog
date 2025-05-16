import { useValues } from 'kea'
import { router } from 'kea-router'
import { now } from 'lib/dayjs'
import { urls } from 'scenes/urls'
import { CalendarHeatMap } from 'scenes/web-analytics/CalendarHeatMap/CalendarHeatMap'

import { ReplayTabs } from '~/types'

import { replayActiveHoursHeatMapLogic } from './replayActiveHoursHeatMapLogic'

export const ReplayActiveHoursHeatMap = (): JSX.Element => {
    const { calendarHeatmapProps, recordingsPerHourLoading } = useValues(
        replayActiveHoursHeatMapLogic({ scene: 'templates' })
    )
    return (
        <div className="w-full flex flex-col">
            <h2>When are your users most active?</h2>
            <p>This heatmap shows you the busiest times of day for your recordings.</p>
            <CalendarHeatMap
                isLoading={recordingsPerHourLoading}
                {...calendarHeatmapProps}
                allAggregationsLabel=""
                getDataTooltip={() => ''}
                getColumnAggregationTooltip={() => ''}
                getRowAggregationTooltip={() => ''}
                getOverallAggregationTooltip={() => ''}
                getOnClickTooltip={(colIndex, rowIndex) => {
                    const day = calendarHeatmapProps.columnLabels[colIndex]
                    const timeRange = rowIndex === undefined ? undefined : calendarHeatmapProps.rowLabels[rowIndex]
                    return `View recordings for ${day}${timeRange ? ` ${timeRange}` : ''}`
                }}
                onClick={(colIndex, rowIndex) => {
                    const daysToSubtract = 6 - colIndex
                    let startDate = now().subtract(daysToSubtract, 'day').startOf('day').utc()
                    let endDate = startDate.clone()

                    if (rowIndex !== undefined) {
                        const startHour = rowIndex * 4
                        const endHour = startHour + 4
                        startDate = startDate.hour(startHour)
                        endDate = endDate.hour(endHour)
                    } else {
                        endDate.add(1, 'day')
                    }

                    router.actions.push(
                        urls.replay(ReplayTabs.Home, {
                            date_from: startDate.toISOString(),
                            date_to: endDate.toISOString(),
                        })
                    )
                }}
                showColumnAggregations={false}
                showRowAggregations={false}
            />
        </div>
    )
}
