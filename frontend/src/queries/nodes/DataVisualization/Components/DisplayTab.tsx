import { IconEye, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { IconEyeHidden } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

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
            <div className="mt-1 mb-2 flex flex-col">
                <LemonSwitch
                    className="flex-1 mb-3 w-full"
                    label="Show legend"
                    checked={chartSettings.showLegend ?? false}
                    onChange={(value) => {
                        updateChartSettings({ showLegend: value })
                    }}
                />
            </div>

            <div className="mt-1 mb-2 flex flex-col">
                <h3>Left Y-axis</h3>
                <LemonField.Pure label="Scale" className="gap-0 mb-3">
                    <LemonSelect
                        value={chartSettings.leftYAxisSettings?.scale ?? 'linear'}
                        options={[
                            { value: 'linear', label: 'Linear' },
                            { value: 'logarithmic', label: 'Logarithmic' },
                        ]}
                        onChange={(value) => {
                            updateChartSettings({ leftYAxisSettings: { scale: value } })
                        }}
                    />
                </LemonField.Pure>
                <LemonSwitch
                    className="flex-1 mb-3 w-full"
                    label="Begin Y-axis at zero"
                    checked={chartSettings.leftYAxisSettings?.startAtZero ?? chartSettings.yAxisAtZero ?? true}
                    onChange={(value) => {
                        updateChartSettings({ leftYAxisSettings: { startAtZero: value } })
                    }}
                />
            </div>

            <div className="mt-1 mb-2 flex flex-col">
                <h3>Right Y-axis</h3>
                <LemonField.Pure label="Scale" className="gap-0 mb-3">
                    <LemonSelect
                        value={chartSettings.rightYAxisSettings?.scale ?? 'linear'}
                        options={[
                            { value: 'linear', label: 'Linear' },
                            { value: 'logarithmic', label: 'Logarithmic' },
                        ]}
                        onChange={(value) => {
                            updateChartSettings({ rightYAxisSettings: { scale: value } })
                        }}
                    />
                </LemonField.Pure>
                <LemonSwitch
                    className="flex-1 mb-3 w-full"
                    label="Begin Y-axis at zero"
                    checked={chartSettings.rightYAxisSettings?.startAtZero ?? chartSettings.yAxisAtZero ?? true}
                    onChange={(value) => {
                        updateChartSettings({ rightYAxisSettings: { startAtZero: value } })
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
                <LemonLabel className="mb-1">Goals</LemonLabel>

                {goalLines.map(({ label, value = 0, displayLabel = true }, goalLineIndex) => (
                    <div className="flex flex-1 gap-1 mb-1" key={`${goalLineIndex}`}>
                        <SeriesLetter className="self-center" hasBreakdown={false} seriesIndex={goalLineIndex} />
                        <LemonInput
                            placeholder="Label"
                            className="grow-2"
                            value={label}
                            suffix={
                                <LemonButton
                                    size="small"
                                    noPadding
                                    icon={displayLabel ? <IconEye /> : <IconEyeHidden />}
                                    tooltip={displayLabel ? 'Display label' : 'Hide label'}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        updateGoalLine(goalLineIndex, 'displayLabel', !displayLabel)
                                    }}
                                />
                            }
                            onChange={(value) => updateGoalLine(goalLineIndex, 'label', value)}
                        />
                        <LemonInput
                            placeholder="Value"
                            className="grow"
                            value={value.toString()}
                            inputMode="numeric"
                            onChange={(value) => updateGoalLine(goalLineIndex, 'value', parseInt(value))}
                        />
                        <LemonButton
                            key="delete"
                            icon={<IconTrash />}
                            status="danger"
                            title="Delete Goal Line"
                            noPadding
                            onClick={() => removeGoalLine(goalLineIndex)}
                        />
                    </div>
                ))}

                <LemonButton className="mt-1" onClick={addGoalLine} icon={<IconPlusSmall />} fullWidth>
                    Add goal line
                </LemonButton>
            </div>
        </div>
    )
}
