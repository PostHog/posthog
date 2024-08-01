import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SeriesLetter } from 'lib/components/SeriesGlyph'

import { displayLogic } from '../displayLogic'

export const DisplayTab = (): JSX.Element => {
    const { goalLines, chartSettings } = useValues(displayLogic)
    const { addGoalLine, updateGoalLine, removeGoalLine, updateChartSettings } = useActions(displayLogic)

    return (
        <div className="flex flex-col w-full">
            <LemonLabel>Chart settings</LemonLabel>

            <div className="mt-1 mb-2">
                <LemonLabel className="mt-2 mb-1">Begin Y axis at zero</LemonLabel>
                <LemonCheckbox
                    checked={chartSettings.yAxisAtZero ?? true}
                    onChange={(value) => {
                        updateChartSettings({ yAxisAtZero: value })
                    }}
                />
            </div>

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
            </div>
            <LemonButton className="mt-1" onClick={() => addGoalLine()} icon={<IconPlusSmall />} fullWidth>
                Add goal line
            </LemonButton>
        </div>
    )
}
