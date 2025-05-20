import { useValues } from 'kea'
import { CalendarHeatMap } from 'scenes/web-analytics/CalendarHeatMap/CalendarHeatMap'

import { getOnClickTooltip, onCellClick, replayActiveHoursHeatMapLogic } from './replayActiveHoursHeatMapLogic'

export const ReplayActiveHoursHeatMap = (): JSX.Element => {
    const { calendarHeatmapProps, recordingsPerHourLoading, isClickable } = useValues(
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
                getOnClickTooltip={getOnClickTooltip}
                onClick={onCellClick}
                isClickable={isClickable}
                showColumnAggregations={false}
                showRowAggregations={false}
            />
        </div>
    )
}
