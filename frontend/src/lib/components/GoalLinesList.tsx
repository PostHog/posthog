import { IconGear, IconTrash } from '@posthog/icons'
import { LemonColorGlyph, LemonColorPicker, LemonLabel, LemonMenu, LemonSegmentedButton } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
                return (
                    <div className="flex flex-1 gap-1 items-center mb-1.5" key={`${goalLineIndex}`}>
                        <LemonColorPicker
                            colors={seriesColor}
                            selectedColor={borderColor || undefined}
                            onSelectColor={(color) => updateGoalLine(goalLineIndex, 'borderColor', color)}
                            showCustomColor
                            customButton={
                                <div className="cursor-pointer">
                                    <LemonColorGlyph color={borderColor} size="small" />
                                </div>
                            }
                        />
                        <LemonInput
                            placeholder="Label"
                            className="grow mx-0.5"
                            value={label}
                            onChange={(value) => updateGoalLine(goalLineIndex, 'label', value)}
                        />
                        <LemonInput
                            type="number"
                            step="any"
                            placeholder="Value"
                            className="w-25 mr-0.5"
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
                                            label: () => {
                                                const disabledReason = displayLabel
                                                    ? undefined
                                                    : 'Enable the label to change its position first.'

                                                const label = (
                                                    <LemonLabel
                                                        className={`font-medium mr-1 ${displayLabel ? 'cursor-pointer' : 'cursor-not-allowed opacity-65'}`}
                                                        onClick={() =>
                                                            displayLabel
                                                                ? updateGoalLine(
                                                                      goalLineIndex,
                                                                      'position',
                                                                      position === 'start' ? 'end' : 'start'
                                                                  )
                                                                : undefined
                                                        }
                                                    >
                                                        Label position
                                                    </LemonLabel>
                                                )

                                                return (
                                                    <div className="flex gap-1 mx-2 mb-2">
                                                        {disabledReason ? (
                                                            <Tooltip title={disabledReason}>
                                                                <span>{label}</span>
                                                            </Tooltip>
                                                        ) : (
                                                            label
                                                        )}
                                                        <LemonSegmentedButton
                                                            value={position ?? 'end'}
                                                            onChange={(value) =>
                                                                updateGoalLine(
                                                                    goalLineIndex,
                                                                    'position',
                                                                    value as 'start' | 'end'
                                                                )
                                                            }
                                                            options={[
                                                                { value: 'start', label: 'Start' },
                                                                { value: 'end', label: 'End' },
                                                            ]}
                                                            size="xsmall"
                                                            data-attr="goal-line-position-selector"
                                                            disabledReason={disabledReason}
                                                        />
                                                    </div>
                                                )
                                            },
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
