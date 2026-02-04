import { IconGear, IconTrash } from '@posthog/icons'
import { LemonColorPicker, LemonMenu } from '@posthog/lemon-ui'

import { getSeriesColor, getSeriesColorPalette } from 'lib/colors'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

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
                        <LemonMenu
                            items={[
                                {
                                    title: 'Label settings',
                                    items: [
                                        {
                                            key: 'display-label',
                                            label: () => (
                                                <LemonSwitch
                                                    label="Show label"
                                                    className="pb-2"
                                                    fullWidth
                                                    checked={displayLabel}
                                                    onChange={(checked) =>
                                                        updateGoalLine(goalLineIndex, 'displayLabel', checked)
                                                    }
                                                    data-attr="goal-line-show-label-switch"
                                                />
                                            ),
                                        },
                                        {
                                            key: 'label-placement',
                                            label: () => (
                                                <LemonSwitch
                                                    label="Label at start"
                                                    className="pb-2"
                                                    fullWidth
                                                    checked={(position ?? 'end') === 'start'}
                                                    onChange={(checked) =>
                                                        updateGoalLine(
                                                            goalLineIndex,
                                                            'position',
                                                            checked ? 'start' : 'end'
                                                        )
                                                    }
                                                    disabledReason={
                                                        displayLabel ? null : 'Enable "Show label" to change placement.'
                                                    }
                                                    data-attr="goal-line-label-placement-switch"
                                                />
                                            ),
                                        },
                                    ],
                                },
                            ]}
                            placement="bottom-end"
                            closeOnClickInside={false}
                        >
                            <LemonButton icon={<IconGear />} title="Goal line settings" noPadding size="small" />
                        </LemonMenu>
                        <LemonButton
                            key="delete"
                            icon={<IconTrash />}
                            status="danger"
                            title="Delete goal line"
                            noPadding
                            size="small"
                            onClick={() => removeGoalLine(goalLineIndex)}
                        />
                    </div>
                )
            })}
        </>
    )
}
