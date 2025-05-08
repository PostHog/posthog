import { useValues } from 'kea'
import { Dayjs } from 'lib/dayjs'
import { CalendarHeatMap } from 'scenes/web-analytics/CalendarHeatMap/CalendarHeatMap'

import { replayActiveHoursHeatMapLogic } from './replayActiveHoursHeatMapLogic'

export const ReplayActiveHoursHeatMap = ({ startDate, endDate }: { startDate: Dayjs; endDate: Dayjs }): JSX.Element => {
    const { calendarHeatmapProps, recordingsPerHourLoading } = useValues(
        replayActiveHoursHeatMapLogic({ scene: 'templates', startDate, endDate })
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
            />
        </div>
    )
}
