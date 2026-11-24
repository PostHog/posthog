import { useId } from 'react'

import { Checkbox, Field, FieldLabel, Input, Separator } from '@posthog/quill'

import { BACK_BUTTON_DEFAULT_TEXT, NewSurvey } from 'scenes/surveys/constants'

import { Survey, SurveyAppearance } from '~/types'

export function QuillSurveyBehaviorOptions({
    survey,
    onAppearanceChange,
    disabledReason,
    onShuffleQuestionsChange,
    onAllowGoBackChange,
}: {
    survey: Survey | NewSurvey
    onAppearanceChange: (appearance: Partial<SurveyAppearance>) => void
    disabledReason?: string
    onShuffleQuestionsChange: (checked: boolean) => void
    onAllowGoBackChange: (checked: boolean) => void
}): JSX.Element {
    const shuffleId = useId()
    const allowGoBackId = useId()
    const backButtonTextId = useId()

    return (
        <div className="flex flex-col gap-3">
            <Field orientation="horizontal" className="w-fit">
                <Checkbox
                    id={shuffleId}
                    checked={!!survey.appearance?.shuffleQuestions}
                    onCheckedChange={onShuffleQuestionsChange}
                    disabledReason={disabledReason}
                />
                <FieldLabel htmlFor={shuffleId}>Shuffle questions</FieldLabel>
            </Field>
            <Separator />
            <Field orientation="horizontal" className="w-fit">
                <Checkbox
                    id={allowGoBackId}
                    checked={!!survey.appearance?.allowGoBack}
                    onCheckedChange={onAllowGoBackChange}
                    disabledReason={disabledReason}
                />
                <FieldLabel htmlFor={allowGoBackId}>Allow going back to previous questions</FieldLabel>
            </Field>
            {survey.appearance?.allowGoBack && (
                <Field className="max-w-xs ps-6">
                    <FieldLabel htmlFor={backButtonTextId}>Back button text</FieldLabel>
                    <Input
                        id={backButtonTextId}
                        placeholder={BACK_BUTTON_DEFAULT_TEXT}
                        value={survey.appearance?.backButtonText ?? ''}
                        onChange={(event) => onAppearanceChange({ backButtonText: event.target.value })}
                        disabledReason={disabledReason}
                    />
                </Field>
            )}
        </div>
    )
}
