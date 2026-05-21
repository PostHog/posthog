import { useActions, useValues } from 'kea'

import { LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { insightLogic } from '../insightLogic'

export function AxisLabelsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="p-1 px-2 flex flex-col gap-2 w-64">
            <div className="flex flex-col gap-1">
                <LemonLabel>X-axis label</LemonLabel>
                <LemonInput
                    size="small"
                    data-attr="trends-x-axis-label-input"
                    value={trendsFilter?.xAxisLabel ?? ''}
                    placeholder="X-axis label"
                    onChange={(value) => updateInsightFilter({ xAxisLabel: value || undefined })}
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Y-axis label</LemonLabel>
                <LemonInput
                    size="small"
                    data-attr="trends-y-axis-label-input"
                    value={trendsFilter?.yAxisLabel ?? ''}
                    placeholder="Y-axis label"
                    onChange={(value) => updateInsightFilter({ yAxisLabel: value || undefined })}
                />
            </div>
        </div>
    )
}
