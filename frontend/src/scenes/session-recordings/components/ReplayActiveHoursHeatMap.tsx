import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { CalendarHeatMap } from 'scenes/web-analytics/CalendarHeatMap/CalendarHeatMap'

import { getOnClickTooltip, onCellClick, replayActiveHoursHeatMapLogic } from './replayActiveHoursHeatMapLogic'

export const ReplayActiveHoursHeatMap = (): JSX.Element => {
    const { timezone } = useValues(teamLogic)
    const { calendarHeatmapProps, recordingsPerHourLoading, isClickable } = useValues(
        replayActiveHoursHeatMapLogic({ scene: 'templates' })
    )

    return (
        <div className="w-full flex flex-col">
            <h2>When are your users most active?</h2>
            <p>This heatmap shows you the busiest times of day for your recordings over the last 7 days.</p>
            <CalendarHeatMap
                isLoading={recordingsPerHourLoading}
                {...calendarHeatmapProps}
                allAggregationsLabel=""
                getDataTooltip={() => ''}
                getColumnAggregationTooltip={() => ''}
                getRowAggregationTooltip={() => ''}
                getOverallAggregationTooltip={() => ''}
                getOnClickTooltip={getOnClickTooltip}
                onClick={(colIndex, rowIndex) => onCellClick(colIndex, rowIndex, timezone)}
                isClickable={isClickable}
                showColumnAggregations={false}
                showRowAggregations={false}
            />
        </div>
    )
}
