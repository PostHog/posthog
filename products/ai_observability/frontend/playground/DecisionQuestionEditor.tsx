import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import {
    MAX_SCORE_LEVELS,
    MIN_OPTIONS,
    type PlaygroundQuestion,
    type PlaygroundQuestionOption,
    type PlaygroundQuestionType,
    createPlaygroundQuestionOption,
} from './playgroundDecisions'

const QUESTION_TYPE_OPTIONS: { value: PlaygroundQuestionType; label: string }[] = [
    { value: 'noul', label: 'Yes or no' },
    { value: 'choice', label: 'Multiple choice' },
    { value: 'score', label: 'Rating scale' },
]

export function DecisionQuestionEditor({
    question,
    disabledReason,
    onChange,
    onRemove,
}: {
    question: PlaygroundQuestion
    disabledReason?: string
    onChange: (question: PlaygroundQuestion) => void
    onRemove: () => void
}): JSX.Element {
    const isChoice = question.type === 'choice'
    const updateOption = (optionId: string, patch: Partial<PlaygroundQuestionOption>): void =>
        onChange({
            ...question,
            options: question.options.map((option) => (option.id === optionId ? { ...option, ...patch } : option)),
        })
    const changeType = (type: PlaygroundQuestionType): void => {
        const options = [...question.options]
        while (options.length < MIN_OPTIONS[type]) {
            options.push(createPlaygroundQuestionOption())
        }
        onChange({ ...question, type, options })
    }

    return (
        <div className="flex flex-col gap-2 border rounded p-2 bg-surface-primary">
            <div className="flex gap-2 items-center">
                <LemonSelect
                    size="small"
                    value={question.type}
                    onChange={(type) => type && changeType(type)}
                    options={QUESTION_TYPE_OPTIONS}
                    disabledReason={disabledReason}
                    data-attr="llma-playground-decision-question-type"
                />
                <LemonInput
                    className="flex-1 min-w-0"
                    size="small"
                    value={question.instructions}
                    onChange={(instructions) => onChange({ ...question, instructions })}
                    placeholder="Does the assistant answer the user's question?"
                    disabled={!!disabledReason}
                />
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    status="danger"
                    noPadding
                    onClick={onRemove}
                    tooltip="Remove question"
                    disabledReason={disabledReason}
                    data-attr="llma-playground-decision-remove-question"
                />
            </div>
            {question.type !== 'noul' && (
                <div className="flex flex-col gap-1 pl-2">
                    <span className="text-xs text-secondary">
                        {isChoice ? 'Options' : 'Scale, from lowest to highest'}
                    </span>
                    {question.options.map((option, index) => (
                        <div key={option.id} className="flex gap-2 items-center">
                            {!isChoice && <span className="text-xs text-secondary w-4 text-right">{index}</span>}
                            <LemonInput
                                className={isChoice ? 'w-40' : 'flex-1 min-w-0'}
                                size="small"
                                value={option.name}
                                onChange={(name) => updateOption(option.id, { name })}
                                placeholder={isChoice ? 'Resolved' : 'Not helpful'}
                                disabled={!!disabledReason}
                            />
                            {isChoice && (
                                <LemonInput
                                    className="flex-1 min-w-0"
                                    size="small"
                                    value={option.description}
                                    onChange={(description) => updateOption(option.id, { description })}
                                    placeholder="What this option means (optional)"
                                    disabled={!!disabledReason}
                                />
                            )}
                            <LemonButton
                                size="small"
                                icon={<IconTrash />}
                                status="danger"
                                noPadding
                                onClick={() =>
                                    onChange({
                                        ...question,
                                        options: question.options.filter((candidate) => candidate.id !== option.id),
                                    })
                                }
                                tooltip={isChoice ? 'Remove option' : 'Remove level'}
                                disabledReason={disabledReason}
                            />
                        </div>
                    ))}
                    <div>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconPlus />}
                            onClick={() =>
                                onChange({
                                    ...question,
                                    options: [...question.options, createPlaygroundQuestionOption()],
                                })
                            }
                            disabledReason={
                                disabledReason ??
                                (!isChoice && question.options.length >= MAX_SCORE_LEVELS
                                    ? `A rating scale takes at most ${MAX_SCORE_LEVELS} levels`
                                    : undefined)
                            }
                            data-attr="llma-playground-decision-add-option"
                        >
                            {isChoice ? 'Option' : 'Level'}
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
