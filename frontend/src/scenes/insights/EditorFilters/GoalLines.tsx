import { useActions, useValues } from 'kea'

import { IconEye, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { IconEyeHidden } from 'lib/lemon-ui/icons'

import { InsightLogicProps } from '~/types'

import { goalLinesLogic } from './goalLinesLogic'

interface GoalLinesProps {
    insightProps: InsightLogicProps
}

export function GoalLines({ insightProps }: GoalLinesProps): JSX.Element {
    const { goalLines } = useValues(goalLinesLogic(insightProps))
    const { addGoalLine, updateGoalLine, removeGoalLine } = useActions(goalLinesLogic(insightProps))

    return (
        <div className="mt-1 mb-2">
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

            <LemonButton type="secondary" onClick={addGoalLine} icon={<IconPlusSmall />} sideIcon={null}>
                Add goal line
            </LemonButton>
        </div>
    )
}
