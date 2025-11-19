import { IconEye, IconTrash } from '@posthog/icons'

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
    return (
        <>
            {goalLines.map(({ label, value = 0, displayLabel = true, position }, goalLineIndex) => (
                <div className="flex flex-1 gap-1 mb-1 items-center" key={`${goalLineIndex}`}>
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
            ))}
        </>
    )
}
