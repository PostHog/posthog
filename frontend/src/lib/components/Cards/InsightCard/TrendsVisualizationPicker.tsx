import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useChartFilterOptions } from 'lib/components/ChartFilter/chartFilterOptions'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

// updateInsightFilter reaches the insight through the same path the card's other display options
// use, so the pick persists and the tile redraws without any extra wiring here.
export function TrendsVisualizationPicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const options = useChartFilterOptions()

    return (
        <LemonSelect
            className="pb-2 px-2"
            fullWidth
            size="small"
            disabledReason={editingDisabledReason}
            value={display || ChartDisplayType.ActionsLineGraph}
            onChange={(value) => updateInsightFilter({ display: value })}
            options={options}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
