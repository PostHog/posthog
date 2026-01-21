import { IconEye, IconTrash } from '@posthog/icons'
import { LemonColorPicker } from '@posthog/lemon-ui'

import { getSeriesColor, getSeriesColorPalette } from 'lib/colors'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { IconEyeHidden } from 'lib/lemon-ui/icons'

import { GoalLine } from '~/queries/schema/schema-general'

interface GoalLinesListProps {
    goalLines: GoalLine[]
    updateGoalLine: (
        goalLineIndex: number,
        key: keyof GoalLine,
        value: NonNullable<string | number | boolean | undefined>
    ) => void
    removeGoalLine: (goalLineIndex: number) => void
}

export function GoalLinesList({ goalLines, updateGoalLine, removeGoalLine }: GoalLinesListProps): JSX.Element {
    const seriesColor = getSeriesColorPalette()
    return (
        <>
            {goalLines.map(({ label, value = 0, displayLabel = true, position, borderColor }, goalLineIndex) => {
                const currentColor = borderColor || getSeriesColor(goalLineIndex)
                return (
                    <div className="flex flex-1 gap-1 mb-1 items-center" key={`${goalLineIndex}`}>
                        <LemonColorPicker
                            colors={seriesColor}
                            selectedColor={borderColor || undefined}
                            onSelectColor={(color) => updateGoalLine(goalLineIndex, 'borderColor', color)}
                            showCustomColor
                            customButton={
                                <div className="cursor-pointer">
                                    <SeriesLetter
                                        className="self-center"
                                        hasBreakdown={false}
                                        seriesIndex={goalLineIndex}
                                        seriesColor={currentColor}
                                    />
                                </div>
                            }
                        />
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
                            type="number"
                            step="any"
                            placeholder="Value"
                            className="grow"
                            value={value}
                            onChange={(value) =>
                                updateGoalLine(
                                    goalLineIndex,
                                    'value',
                                    value !== undefined && !Number.isNaN(value) ? value : 0
                                )
                            }
                        />
                        <LemonSegmentedButton
                            value={position ?? 'end'}
                            onChange={(value) => updateGoalLine(goalLineIndex, 'position', value as 'start' | 'end')}
                            options={[
                                { value: 'start', label: 'Start' },
                                { value: 'end', label: 'End' },
                            ]}
                            size="xsmall"
                            data-attr="goal-line-position-selector"
                        />
                        <LemonButton
                            key="delete"
                            icon={<IconTrash />}
                            status="danger"
                            title="Delete goal line"
                            noPadding
                            onClick={() => removeGoalLine(goalLineIndex)}
                        />
                    </div>
                )
            })}
        </>
    )
}
