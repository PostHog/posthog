import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SeriesLetter } from 'lib/components/SeriesGlyph'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'

export const DisplayTab = (): JSX.Element => {
    const { visualizationType } = useValues(dataVisualizationLogic)
    const { goalLines, chartSettings } = useValues(displayLogic)
    const { addGoalLine, updateGoalLine, removeGoalLine, updateChartSettings } = useActions(displayLogic)

    const isStackedBarChart = visualizationType === ChartDisplayType.ActionsStackedBar

    return (
        <div className="flex flex-col w-full">
            <div className="mt-1 mb-2 flex">
                <LemonSwitch
                    className="flex-1"
                    label="Begin Y axis at zero"
                    checked={chartSettings.yAxisAtZero ?? true}
                    onChange={(value) => {
                        updateChartSettings({ yAxisAtZero: value })
                    }}
                />
            </div>

            {isStackedBarChart && (
                <div className="mt-1 mb-2 flex">
                    <LemonSwitch
                        className="flex-1"
                        label="Stack bars 100%"
                        checked={chartSettings.stackBars100 ?? false}
                        onChange={(value) => {
                            updateChartSettings({ stackBars100: value })
                        }}
                    />
                </div>
            )}

            <div className="mt-1 mb-2">
                <LemonLabel className="mb-1">Goal line</LemonLabel>
                {goalLines.map((goalLine, goalLineIndex) => (
                    <div className="flex flex-1 gap-1 mb-1" key={`${goalLineIndex}`}>
                        <SeriesLetter className="self-center" hasBreakdown={false} seriesIndex={goalLineIndex} />
                        <LemonInput
                            placeholder="Label"
                            className="grow-2"
                            value={goalLine.label}
                            onChange={(value) => updateGoalLine(goalLineIndex, 'label', value)}
                        />
                        <LemonInput
                            placeholder="Value"
                            className="grow"
                            value={(goalLine.value ?? 0).toString()}
                            inputMode="numeric"
                            onChange={(value) => updateGoalLine(goalLineIndex, 'value', parseInt(value))}
                        />
                        <LemonButton
                            key="delete"
                            icon={<IconTrash />}
                            status="danger"
                            title="Delete Y-series"
                            noPadding
                            onClick={() => removeGoalLine(goalLineIndex)}
                        />
                    </div>
                ))}
                <LemonButton className="mt-1" onClick={() => addGoalLine()} icon={<IconPlusSmall />} fullWidth>
                    Add goal line
                </LemonButton>
            </div>
        </div>
    )
}
