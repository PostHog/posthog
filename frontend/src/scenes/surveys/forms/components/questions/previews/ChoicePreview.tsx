import { useCallback } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { FormChoiceQuestion, FormQuestionType, FormQuestion } from 'scenes/surveys/forms/formTypes'

import { QuestionPreviewProps } from '../questionTypeRegistry'

export function ChoicePreview({ question, onUpdate }: QuestionPreviewProps): JSX.Element {
    const q = question as FormChoiceQuestion
    const isSingle = q.type === FormQuestionType.SingleChoice

    const updateChoice = useCallback(
        (index: number, value: string): void => {
            const newChoices = [...q.choices]
            newChoices[index] = value
            onUpdate({ ...q, choices: newChoices } as FormQuestion)
        },
        [q, onUpdate]
    )

    const addChoice = useCallback(
        (isOpenChoice?: boolean): void => {
            const newIndex = q.hasOpenChoice ? q.choices.length - 1 : q.choices.length
            onUpdate({
                ...q,
                choices: q.choices.toSpliced(newIndex, 0, isOpenChoice ? 'Other' : `Option ${q.choices.length + 1}`),
                hasOpenChoice: (isOpenChoice || q.hasOpenChoice) ?? false,
            } as FormQuestion)
        },
        [q, onUpdate]
    )

    const removeChoice = useCallback(
        (index: number): void => {
            if (q.choices.length <= 1) {
                return
            }
            const isRemovingOpenChoice = q.hasOpenChoice && index === q.choices.length - 1
            onUpdate({
                ...q,
                choices: q.choices.filter((_, i) => i !== index),
                hasOpenChoice: isRemovingOpenChoice ? false : q.hasOpenChoice,
            } as FormQuestion)
        },
        [q, onUpdate]
    )

    return (
        <div className="mt-2 flex flex-col gap-1.5">
            {q.choices.map((choice, index) => (
                <div key={index} className="flex items-center gap-2 group">
                    <div
                        className={`w-4 h-4 border-2 border-border flex-shrink-0 ${isSingle ? 'rounded-full' : 'rounded-sm'}`}
                    />
                    <LemonInput
                        size="small"
                        value={choice}
                        onChange={(value) => updateChoice(index, value)}
                        className="flex-1"
                        fullWidth
                        suffix={
                            q.hasOpenChoice && index === q.choices.length - 1 ? (
                                <LemonTag type="highlight">open-ended</LemonTag>
                            ) : undefined
                        }
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconTrash />}
                        status="default"
                        className="opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => removeChoice(index)}
                        tooltip="Remove option"
                    />
                </div>
            ))}
            <div className="flex gap-2 mt-1">
                <LemonButton size="xsmall" icon={<IconPlus />} status="default" onClick={() => addChoice()}>
                    Add option
                </LemonButton>
                {!q.hasOpenChoice && (
                    <LemonButton size="xsmall" icon={<IconPlus />} status="default" onClick={() => addChoice(true)}>
                        Add open-ended choice
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
